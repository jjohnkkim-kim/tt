"""대시보드 '오늘 할 일' 계산: 기간 필터에 맞춰 신규·관심제품·마감 임박·낙찰·유찰·재공고·계약 종료 임박을 한 번에 만든다.

데이터가 없는 항목은 비워 둔다(만들어 내지 않는다). 낙찰·유찰은 개찰 며칠 뒤에 공개되므로 최근 기간은 비어 있을 수 있다.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from .data import Snapshot, open_bids, pharma_only
from .metrics import expiring_contracts

MEDIUM, LOW = 55, 35          # 매칭 신뢰도 하한 (hbr.analytics.matching.LEVELS 와 같은 값)


def _in_range(s: pd.Series, start: date, end: date) -> pd.Series:
    d = pd.to_datetime(s, errors="coerce")
    return (d >= pd.Timestamp(start)) & (d < pd.Timestamp(end) + pd.Timedelta(days=1))


def _per_bid(df: pd.DataFrame) -> pd.DataFrame:
    """같은 공고(투찰업체별 중복 행)는 한 건으로 센다."""
    keys = [c for c in ("bid_ntce_no", "bid_ntce_ord") if c in df]
    return df.drop_duplicates(keys) if keys and not df.empty else df


def build_overview(snap: Snapshot, lc: pd.DataFrame, mt: pd.DataFrame, today: date, start: date, end: date,
                   pharma: bool = True, closing_days: int = 7, has_products: bool = False) -> dict:
    """lc: lifecycle(snap.bids 와 같은 인덱스), mt: 제품 매칭(같은 인덱스). 둘 다 비어 있어도 된다."""
    t = pd.Timestamp(today)
    bids = snap.bids if snap.bids is not None else pd.DataFrame()
    bids = pharma_only(bids) if pharma and not bids.empty else bids
    empty = pd.DataFrame()

    new = bids[_in_range(bids["bid_date"], start, end)] if not bids.empty else empty
    new = new.sort_values(["bid_date", "budget"], ascending=[False, False]) if not new.empty else new
    lc_new = lc.reindex(new.index) if lc is not None and not lc.empty and not new.empty else pd.DataFrame(index=new.index)
    mt_new = mt.reindex(new.index) if mt is not None and not mt.empty and not new.empty else pd.DataFrame(index=new.index)

    score = pd.to_numeric(mt_new.get("match_score"), errors="coerce") if "match_score" in mt_new else pd.Series(index=new.index, dtype=float)
    related = new[score.fillna(0) >= MEDIUM] if not new.empty else empty
    review = new[(score.fillna(0) >= LOW) & (score.fillna(0) < MEDIUM)] if not new.empty else empty
    rebids = new[lc_new["is_rebid"].fillna(False).astype(bool)] if "is_rebid" in lc_new and not new.empty else empty

    ob = open_bids(bids, today) if not bids.empty else empty
    closing = (ob[ob["deadline"].notna() & (ob["deadline"] >= t) & (ob["deadline"] < t + pd.Timedelta(days=closing_days + 1))].sort_values("deadline")
               if not ob.empty else empty)

    def results(df):
        if df is None or df.empty or "award_date" not in df:
            return empty
        d = pharma_only(df) if pharma else df
        d = d[_in_range(d["award_date"], start, end)] if not d.empty else d
        return _per_bid(d.sort_values("award_date", ascending=False)) if not d.empty else d

    awarded, failed = results(snap.awards), results(snap.failed)
    comp = awarded[~awarded["is_own"].astype(bool)] if not awarded.empty and "is_own" in awarded else awarded

    exp = expiring_contracts(snap, today, 90)
    con = pharma_only(snap.contracts) if snap.contracts is not None and not snap.contracts.empty else empty
    return {
        "kpi": {"new": len(new), "related": len(related), "review": len(review), "closing": len(closing), "rebid": len(rebids),
                "awarded": len(awarded), "failed": len(failed), "expiring": len(exp), "competitor_awards": len(comp)},
        "new": new, "related": related, "review": review, "closing": closing, "rebids": rebids, "lc_new": lc_new, "mt_new": mt_new,
        "awarded": awarded, "failed": failed, "expiring": exp,
        "contracts_total": len(con), "contracts_with_end": int(con["end_date"].notna().sum()) if not con.empty and "end_date" in con else 0,
        "has_products": has_products,
    }


def closing_bucket(closing: pd.DataFrame, today: date, days: int) -> pd.DataFrame:
    """마감 임박 목록을 D-day 구간(1/3/7일 이내)으로 자른다."""
    if closing is None or closing.empty:
        return closing
    t = pd.Timestamp(today)
    return closing[closing["deadline"] < t + pd.Timedelta(days=days + 1)]
