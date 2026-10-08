"""대시보드/리포트/코파일럿이 공유하는 지표 계산 (한 곳에서 정의해 숫자 불일치 방지)."""
from __future__ import annotations

from datetime import date

import pandas as pd

from .data import Snapshot, open_bids, pharma_only
from .scoring import Opportunity


def kpis(snap: Snapshot, opps: list[Opportunity], today: date, new_days: int = 7) -> dict:
    t = pd.Timestamp(today)
    bids = pharma_only(snap.bids)
    ob = open_bids(bids, today)
    con = pharma_only(snap.contracts)
    aw = pharma_only(snap.awards)
    new_bids = bids[bids["bid_date"] >= t - pd.Timedelta(days=new_days)] if not bids.empty else bids
    soon = ob[ob["deadline"].notna() & (ob["deadline"] <= t + pd.Timedelta(days=7, hours=23))] if not ob.empty else ob
    exp = pd.Series(dtype=float)
    if not con.empty:
        d = (con["end_date"] - t).dt.days
        exp = d[(d >= 0) & (d <= 90)]
    comp_new = aw[(~aw["is_own"]) & (aw["award_date"] >= t - pd.Timedelta(days=30))] if not aw.empty else aw
    return {
        "new_bids": len(new_bids), "open_bids": len(ob), "closing_soon": len(soon),
        "expiring_90": int(len(exp)), "competitor_awards_30d": len(comp_new),
        "expected_amount": float(sum(o.est_amount for o in opps)),
        "new_days": new_days,
    }


def expiring_contracts(snap: Snapshot, today: date, within: int = 90) -> pd.DataFrame:
    con = pharma_only(snap.contracts)
    if con.empty:
        return con
    con = con[con["end_date"].notna()].copy()
    con["d_day"] = (con["end_date"] - pd.Timestamp(today)).dt.days
    con = con[(con["d_day"] >= 0) & (con["d_day"] <= within)]
    return con.sort_values("d_day")


def share_by_year(snap: Snapshot, metric: str = "amount") -> pd.DataFrame:
    """연도×업체 수주 집계 (점유율 변화)."""
    aw = pharma_only(snap.awards)
    if aw.empty:
        return pd.DataFrame(columns=["year", "competitor", "amount", "count", "share"])
    aw = aw.assign(year=aw["award_date"].dt.year)
    g = aw.groupby(["year", "competitor"]).agg(amount=("award_amount", "sum"),
                                               count=("award_key", "count")).reset_index()
    g["share"] = g["amount"] / g.groupby("year")["amount"].transform("sum").replace(0, pd.NA)
    return g


def competitor_hospitals(snap: Snapshot, competitor: str, since: date | None = None) -> pd.DataFrame:
    aw = pharma_only(snap.awards)
    if aw.empty:
        return aw
    aw = aw[aw["competitor"].str.lower() == competitor.lower()]
    if since is not None:
        aw = aw[aw["award_date"] >= pd.Timestamp(since)]
    return (aw.groupby("hospital").agg(count=("award_key", "count"), amount=("award_amount", "sum"),
                                       last=("award_date", "max")).reset_index()
              .sort_values(["count", "amount"], ascending=False))


# ── 대시보드(공고 중심) ─────────────────────────────────────────
def bid_overview(bids: pd.DataFrame, today: date, pharma: bool = True, new_days: int = 7, closing_days: int = 7,
                 trend_days: int = 30) -> dict:
    """입찰공고 대시보드에 필요한 숫자·목록·차트 데이터를 한 번에 계산한다."""
    t = pd.Timestamp(today)
    empty = pd.DataFrame()
    base = pharma_only(bids) if pharma else bids
    if base is None or base.empty:
        days = pd.date_range(t - pd.Timedelta(days=trend_days - 1), t)
        return {"kpi": {"new": 0, "open": 0, "closing": 0, "budget": 0.0, "open_all": 0}, "new": empty, "closing": empty,
                "trend": pd.DataFrame({"날짜": days, "건수": 0}), "tags": pd.DataFrame(columns=["분류", "건수"]),
                "hospitals": pd.DataFrame(columns=["기관", "건수"]), "empty": True}
    ob = open_bids(base, today)
    new = base[base["bid_date"] >= t - pd.Timedelta(days=new_days - 1)].sort_values(["bid_date", "budget"], ascending=[False, False])
    closing = ob[ob["deadline"].notna() & (ob["deadline"] >= t) & (ob["deadline"] < t + pd.Timedelta(days=closing_days + 1))] \
        .sort_values("deadline")
    days = pd.date_range(t - pd.Timedelta(days=trend_days - 1), t)
    counts = base.assign(d=base["bid_date"].dt.normalize()).groupby("d").size().reindex(days, fill_value=0)
    trend = pd.DataFrame({"날짜": days, "건수": counts.values})
    tag_rows = [tag for tags in (ob["product_tags"] if "product_tags" in ob else []) if isinstance(tags, (list, tuple)) for tag in tags]
    tags = (pd.Series(tag_rows, dtype=object).value_counts().rename_axis("분류").reset_index(name="건수")
            if tag_rows else pd.DataFrame(columns=["분류", "건수"]))
    hosp = (ob["hospital"].dropna().value_counts().head(8).rename_axis("기관").reset_index(name="건수")
            if "hospital" in ob and not ob.empty else pd.DataFrame(columns=["기관", "건수"]))
    return {"kpi": {"new": len(new), "open": len(ob), "closing": len(closing),
                    "budget": float(ob["budget"].fillna(0).sum()) if "budget" in ob else 0.0, "open_all": len(open_bids(bids, today))},
            "new": new, "closing": closing, "trend": trend, "tags": tags, "hospitals": hosp, "empty": False}
