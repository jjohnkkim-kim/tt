"""회사별 기회 점수(병원 단위)와 '다음 입찰 예상'.

기존 scoring.py 는 계약 종료일(이 API 에는 없음)에 크게 기대서 대부분 같은 점수가 나왔다. 여기서는 실제로 가진 데이터만 쓴다.
 · 제품 적합도 35  : 이 회사 관심제품과 맞는 진행중 공고 (HIGH/MEDIUM)
 · 마감 임박 20    : 맞는 공고 중 가장 가까운 마감
 · 시장 규모 20    : 최근 1년 의약품 공고 예산 + 낙찰 금액 (병원 간 로그 상대평가)
 · 경쟁 여지 15    : 최근 180일 낙찰에서 자사 점유율이 낮고 업체가 여럿일수록 ↑ (낙찰 5건 미만이면 '데이터 부족')
 · 반복 구매 10    : 3회 이상 반복된 품목의 다음 입찰 예상(추정)이 곧 다가오는지 (반복 품목이 없으면 '데이터 부족')
데이터 부족 항목은 0점으로 깎지 않고 가중치에서 빼서 나머지로 다시 계산하며, 어떤 항목이 빠졌는지 함께 돌려준다.
관심제품이 없으면 점수를 만들지 않는다.
"""
from __future__ import annotations

import math
from datetime import date

import pandas as pd

from .competitors import MIN_SHARE_N, prepare
from .data import Snapshot, open_bids, pharma_only
from .patterns import repeated_items

WEIGHTS = {"fit": 35, "timing": 20, "market": 20, "competition": 15, "repeat": 10}
LABELS = {"fit": "제품 적합도", "timing": "마감 임박", "market": "시장 규모", "competition": "경쟁 여지", "repeat": "반복 구매"}
GRADES = ((75, "높음"), (55, "보통"), (0, "관찰"))
STRONG = {"HIGH", "MEDIUM"}


def grade_of(score: float) -> str:
    return next(g for lo, g in GRADES if score >= lo)


def fit_score(high: int, medium: int) -> float:
    if high >= 2:
        return 100.0
    if high == 1:
        return 80.0
    return 50.0 if medium else 0.0


def timing_score(days_left: int | None) -> float:
    if days_left is None:
        return 0.0
    return 100.0 if days_left <= 3 else 80.0 if days_left <= 7 else 60.0 if days_left <= 14 else 40.0


def market_scores(amounts: dict) -> dict:
    top = max(amounts.values(), default=0)
    if top <= 0:
        return {k: 0.0 for k in amounts}
    return {k: 100 * math.log1p(v) / math.log1p(top) for k, v in amounts.items()}


def competition_score(own_share: float, vendors: int) -> float:
    """자사 점유율이 낮을수록(빈틈), 업체가 많을수록(경합) 진입 여지가 크다."""
    return round(0.6 * (1 - own_share) * 100 + 0.4 * min(vendors, 5) / 5 * 100, 1)


def repeat_score(days_to_next: int | None) -> float | None:
    """None 이면 반복 품목이 없어 판단 불가."""
    if days_to_next is None:
        return None
    if days_to_next < -14:
        return 20.0
    return 100.0 if days_to_next <= 45 else 60.0 if days_to_next <= 90 else 30.0


def forecast(bids: pd.DataFrame, today: date, name_of=None, horizon_days: int = 120) -> pd.DataFrame:
    """병원별로 3회 이상 반복된 품목의 다음 입찰 예상(추정). 이미 지난 지 14일 넘은 건 제외."""
    cols = ["병원", "hospital_id", "품목", "횟수", "평균 간격(일)", "마지막 공고일", "다음 입찰 예상(추정)", "D-day"]
    if bids is None or bids.empty:
        return pd.DataFrame(columns=cols)
    t = pd.Timestamp(today)
    parts = []
    for hid, g in bids.groupby("hospital_id"):
        r = repeated_items(g)
        if r.empty:
            continue
        r = r.assign(hospital_id=int(hid), D=(r["다음 입찰 예상(추정)"] - t).dt.days)
        parts.append(r)
    if not parts:
        return pd.DataFrame(columns=cols)
    d = pd.concat(parts, ignore_index=True)
    d = d[(d["D"] >= -14) & (d["D"] <= horizon_days)].rename(columns={"D": "D-day"})
    d["병원"] = d["hospital_id"].map(name_of) if name_of else d["hospital_id"].astype(str)
    return d.sort_values("D-day").reset_index(drop=True)[cols]


def company_opportunities(snap: Snapshot, matches: pd.DataFrame, today: date) -> pd.DataFrame:
    """병원별 기회 점수 표. 열: hospital_id, 병원, 점수, 등급, 항목별 점수(components: dict), 빠진 항목(missing), 근거(reasons), 진행공고, 맞는공고."""
    out_cols = ["hospital_id", "병원", "점수", "등급", "components", "missing", "reasons", "진행공고", "맞는공고"]
    bids = pharma_only(snap.bids)
    if bids is None or bids.empty or matches is None or matches.empty:
        return pd.DataFrame(columns=out_cols)
    t = pd.Timestamp(today)
    aw = prepare(pharma_only(snap.awards)) if snap.awards is not None and not snap.awards.empty else pd.DataFrame()
    aw180 = aw[aw["award_date"] >= t - pd.Timedelta(days=180)] if not aw.empty else aw
    ob = open_bids(bids, today)
    m = matches.reindex(ob.index)
    strong = ob[m["match_level"].isin(STRONG)] if not ob.empty else ob
    fc = forecast(bids, today, snap.hospital_name)

    market = {}
    for hid, g in bids.groupby("hospital_id"):
        b = g[g["bid_date"] >= t - pd.Timedelta(days=365)]["budget"].fillna(0).sum()
        a = aw[(aw["hospital_id"] == hid) & (aw["award_date"] >= t - pd.Timedelta(days=365))]["award_amount"].fillna(0).sum() if not aw.empty else 0
        market[int(hid)] = float(b + a)
    ms = market_scores(market)

    rows = []
    for hid in market:
        comps, missing, reasons = {}, [], []
        s = strong[strong["hospital_id"] == hid] if not strong.empty else strong
        lv = m.loc[s.index, "match_level"] if not s.empty else pd.Series(dtype=object)
        high, med = int((lv == "HIGH").sum()), int((lv == "MEDIUM").sum())
        comps["fit"] = fit_score(high, med)
        if high or med:
            reasons.append(f"내 제품과 맞는 진행 공고 {high + med}건 (확실 {high} · 가능성 {med})")
        dl = pd.to_datetime(s["deadline"], errors="coerce").dropna() if not s.empty else pd.Series(dtype="datetime64[ns]")
        left = int((dl.min().tz_localize(None) - t).days) if not dl.empty and dl.min().tzinfo else (int((dl.min() - t).days) if not dl.empty else None)
        comps["timing"] = timing_score(left)
        if left is not None:
            reasons.append(f"가장 가까운 마감 D-{max(left, 0)}")
        comps["market"] = round(ms.get(hid, 0.0), 1)
        if comps["market"] >= 75:
            reasons.append("의약품 시장 규모가 큰 병원")
        a = aw180[aw180["hospital_id"] == hid] if not aw180.empty else aw180
        if len(a) >= MIN_SHARE_N:
            own = float(a["is_own"].mean()) if "is_own" in a else 0.0
            comps["competition"] = competition_score(own, a["vendor_key"].nunique())
            if own == 0:
                reasons.append(f"최근 180일 낙찰 {len(a)}건 중 자사 낙찰 없음")
        else:
            missing.append("competition")
        f = fc[fc["hospital_id"] == hid] if not fc.empty else fc
        rs = repeat_score(int(f["D-day"].min()) if not f.empty else None)
        if rs is None:
            missing.append("repeat")
        else:
            comps["repeat"] = rs
            reasons.append(f"반복 품목 다음 입찰 예상(추정) D-{int(f['D-day'].min())}")
        w = {k: WEIGHTS[k] for k in comps}
        score = round(sum(comps[k] * w[k] for k in comps) / sum(w.values()), 1)
        rows.append({"hospital_id": hid, "병원": snap.hospital_name(hid), "점수": score, "등급": grade_of(score),
                     "components": comps, "missing": missing, "reasons": reasons,
                     "진행공고": int(len(ob[ob["hospital_id"] == hid])) if not ob.empty else 0, "맞는공고": high + med})
    df = pd.DataFrame(rows, columns=out_cols).sort_values(["점수", "맞는공고"], ascending=False).reset_index(drop=True)
    return df
