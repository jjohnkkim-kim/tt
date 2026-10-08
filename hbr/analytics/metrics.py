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
