"""병원 구매 패턴: 입찰 빈도, 반복 입찰 품목·주기, 재공고·유찰 빈도, 계약기간.

원칙: 모든 값은 표본 수(n)와 충분 여부(sufficient)를 함께 돌려주고, 부족하면 값을 만들지 않는다 (화면에서 '데이터 부족').
'다음 입찰 예상'은 같은 품목이 3회 이상 반복된 경우에만 '추정'으로 계산한다.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from .data import Snapshot, pharma_only
from .lifecycle import core_title, is_rebid_title

MIN_BIDS_FOR_RATE = 10        # 재공고 비율을 말할 최소 공고 수
MIN_RESULTS_FOR_RATE = 5      # 유찰 비율을 말할 최소 개찰 결과 수
MIN_REPEATS = 3               # 주기를 말할 최소 반복 횟수
MIN_CONTRACTS = 3             # 평균 계약기간을 말할 최소 계약 수(시작·종료일이 모두 있는 것)


def _metric(value, n: int, sufficient: bool, basis: str) -> dict:
    return {"value": value if sufficient else None, "n": n, "sufficient": sufficient, "basis": basis}


def _per_bid(df: pd.DataFrame) -> pd.DataFrame:
    keys = [c for c in ("bid_ntce_no", "bid_ntce_ord") if c in df]
    return df.drop_duplicates(keys) if keys and not df.empty else df


def repeated_items(bids: pd.DataFrame) -> pd.DataFrame:
    """같은 품목이 (재공고를 뺀) 새 공고로 반복된 횟수와 간격. MIN_REPEATS 회 이상만."""
    cols = ["품목", "횟수", "평균 간격(일)", "마지막 공고일", "다음 입찰 예상(추정)"]
    if bids is None or bids.empty:
        return pd.DataFrame(columns=cols)
    bids = bids[~bids["title"].map(is_rebid_title)]          # 재공고는 같은 입찰의 반복이지 새 구매 주기가 아니다
    if bids.empty:
        return pd.DataFrame(columns=cols)
    d = bids.assign(_core=bids["title"].map(core_title))
    rows = []
    for core, g in d.groupby("_core"):
        dates = sorted(pd.to_datetime(g["bid_date"], errors="coerce").dt.normalize().dropna().unique())
        if not core or len(dates) < MIN_REPEATS:
            continue
        gaps = pd.Series(dates).diff().dropna().dt.days
        gaps = gaps[gaps > 0]
        if gaps.empty:
            continue
        interval = float(gaps.median())
        last = pd.Timestamp(dates[-1])
        rows.append({"품목": str(g.sort_values("bid_date").iloc[-1]["title"]), "횟수": len(dates), "평균 간격(일)": round(interval, 1),
                     "마지막 공고일": last, "다음 입찰 예상(추정)": last + pd.Timedelta(days=round(interval))})
    return pd.DataFrame(rows, columns=cols).sort_values(["횟수", "마지막 공고일"], ascending=False).reset_index(drop=True) if rows else pd.DataFrame(columns=cols)


def hospital_pattern(snap: Snapshot, hospital_id, today: date, pharma: bool = True) -> dict:
    t = pd.Timestamp(today)

    def mine(df):
        if df is None or df.empty or "hospital_id" not in df:
            return pd.DataFrame()
        d = pharma_only(df) if pharma else df
        return d[d["hospital_id"] == hospital_id] if not d.empty else d

    bids, aw, fl, con = mine(snap.bids), mine(snap.awards), mine(snap.failed), mine(snap.contracts)
    counts = {}
    for label, days in (("최근 1개월", 30), ("최근 3개월", 90), ("최근 1년", 365)):
        counts[label] = int((bids["bid_date"] >= t - pd.Timedelta(days=days)).sum()) if not bids.empty else 0
    first = bids["bid_date"].min() if not bids.empty else None
    held_days = int((t - first).days) + 1 if first is not None and not pd.isna(first) else 0

    n_bids = len(bids)
    rebid_n = int(bids["title"].map(is_rebid_title).sum()) if n_bids else 0
    awarded, failed = _per_bid(aw), _per_bid(fl)
    n_res = len(awarded) + len(failed)
    rep = repeated_items(bids)
    ranges = []
    if not con.empty and {"start_date", "end_date"} <= set(con.columns):
        both = con.dropna(subset=["start_date", "end_date"])
        ranges = ((both["end_date"] - both["start_date"]).dt.days / 30.4).tolist()
    top_items = (bids.assign(품목=bids["title"].map(core_title)).groupby("품목").agg(공고수=("title", "size"), 대표제목=("title", "last")).reset_index()
                 .sort_values("공고수", ascending=False).head(5)) if n_bids else pd.DataFrame(columns=["품목", "공고수", "대표제목"])
    return {
        "counts": counts, "held_days": held_days, "n_bids": n_bids,
        "rebid_rate": _metric(round(rebid_n / n_bids * 100, 1) if n_bids else None, n_bids, n_bids >= MIN_BIDS_FOR_RATE,
                              f"재공고 표시가 있는 공고 {rebid_n}건 / 전체 공고 {n_bids}건"),
        "fail_rate": _metric(round(len(failed) / n_res * 100, 1) if n_res else None, n_res, n_res >= MIN_RESULTS_FOR_RATE,
                             f"유찰 {len(failed)}건 / 개찰 결과 {n_res}건"),
        "cycle_days": _metric(round(float(rep["평균 간격(일)"].median()), 1) if not rep.empty else None, len(rep), not rep.empty,
                              f"같은 품목이 {MIN_REPEATS}회 이상 반복된 {len(rep)}개 품목의 간격(중앙값)"),
        "contract_months": _metric(round(float(pd.Series(ranges).median()), 1) if len(ranges) >= MIN_CONTRACTS else None, len(ranges), len(ranges) >= MIN_CONTRACTS,
                                   f"시작·종료일이 모두 있는 계약 {len(ranges)}건"),
        "repeated": rep, "top_items": top_items,
    }
