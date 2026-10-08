"""AI Opportunity Score (100점) — 투명한 규칙 기반 점수. LLM 은 설명/행동 문구에만 쓴다.

가중치: 계약만료 임박성 30 · 시장규모 25 · 경쟁강도 20 · 최근 낙찰패턴 15 · 입찰빈도 10
각 항목은 0~100 으로 정규화 후 가중합한다. 모든 계산은 의약품 관련(is_pharma) 데이터만 사용.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

import pandas as pd

from ..constants import REBID_LEAD_DAYS, SCORE_WEIGHTS
from ..store.repo import Repo
from ..utils import fmt_won, today_kst
from .data import Snapshot, load_snapshot, open_bids, pharma_only


@dataclass
class Opportunity:
    hospital_id: int
    hospital: str
    score: float
    components: dict[str, float]
    days_to_expiry: int | None
    expiry_date: date | None
    expected_rebid: date | None
    market_amount_3y: float
    est_amount: float
    top_vendor: str | None
    competitor_streak: int
    open_bid_count: int
    reasons: list[str] = field(default_factory=list)

    @property
    def grade(self) -> str:
        return "최우선" if self.score >= 90 else "높음" if self.score >= 75 else "보통" if self.score >= 60 else "관찰"

    def to_row(self, score_date: date) -> dict:
        d = asdict(self)
        return {"hospital_id": self.hospital_id, "score_date": score_date, "score": self.score,
                "components": self.components, "days_to_expiry": self.days_to_expiry,
                "est_amount": self.est_amount, "reasons": self.reasons,
                "detail": {k: d[k] for k in ("expiry_date", "expected_rebid", "market_amount_3y",
                                             "top_vendor", "competitor_streak", "open_bid_count")}}


# ── 항목별 점수 함수 (단위 테스트 대상) ───────────────────────────
def expiry_score(days: int | None) -> float:
    if days is None:
        return 25.0            # 계약 정보 없음: 신규 진입 여지는 있으나 시점 불명
    if days < 0:
        return 70.0 if days >= -90 else 30.0   # 이미 종료: 재입찰 진행/지연 가능성
    if days <= 30:
        return 100.0
    if days <= 60:
        return 92.0
    if days <= 90:
        return 82.0
    if days <= 180:
        return 60.0
    if days <= 365:
        return 35.0
    return 15.0


def competition_score(distinct_vendors: int) -> float:
    """경합 시장일수록 신규 진입 가능성이 높다 (단일 공급사 고착 시장은 낮게)."""
    return {0: 30.0, 1: 45.0, 2: 70.0, 3: 90.0}.get(distinct_vendors, 100.0)


def pattern_score(streak: int, own_recent: bool, has_awards: bool) -> float:
    """최근 낙찰패턴: 경쟁사(자사 제외) 연속 수주일수록 공략 명분↑."""
    if streak >= 3:
        return 100.0
    if streak == 2:
        return 85.0
    if streak == 1:
        return 60.0
    if own_recent:
        return 30.0            # 자사 수주 중 → 방어
    return 20.0 if has_awards else 15.0


def frequency_score(bid_count_24m: int) -> float:
    return min(100.0, bid_count_24m / 6 * 100)


def market_scores(amounts: dict[int, float]) -> dict[int, float]:
    """로그 스케일 상대평가 (최대 병원 = 100)."""
    if not amounts:
        return {}
    top = max(amounts.values())
    if top <= 0:
        return {k: 0.0 for k in amounts}
    return {k: 100 * math.log1p(v) / math.log1p(top) for k, v in amounts.items()}


# ── 계산 ─────────────────────────────────────────────────────
def _next_expiry(contracts: pd.DataFrame, today: date):
    """가장 가까운 '앞으로의' 종료일, 없으면 최근 90일 내 종료 건."""
    ends = contracts["end_date"].dropna()
    if ends.empty:
        return None, None
    days = (ends - pd.Timestamp(today)).dt.days
    upcoming = days[days >= 0]
    if not upcoming.empty:
        idx = upcoming.idxmin()
    else:
        recent = days[days >= -90]
        if recent.empty:
            return None, None
        idx = recent.idxmax()
    return int(days[idx]), ends[idx].date()


def compute_opportunities(snap: Snapshot, today: date | None = None) -> list[Opportunity]:
    today = today or today_kst()
    t = pd.Timestamp(today)
    bids, awards, contracts = (pharma_only(x) for x in (snap.bids, snap.awards, snap.contracts))
    cut3y, cut1y, cut2y = t - pd.DateOffset(years=3), t - pd.DateOffset(years=1), t - pd.DateOffset(years=2)

    hospital_ids = set(snap.hospitals["id"]) if not snap.hospitals.empty else set()
    # 의약품 관련 이력이 하나도 없는 병원은 점수 대상에서 제외
    active = {h for df in (bids, awards, contracts) if not df.empty for h in df["hospital_id"].dropna()}
    hospital_ids &= {int(h) for h in active}

    market: dict[int, float] = {}
    per: dict[int, dict] = {}
    for hid in hospital_ids:
        a = awards[(awards["hospital_id"] == hid)] if not awards.empty else awards
        c = contracts[(contracts["hospital_id"] == hid)] if not contracts.empty else contracts
        b = bids[(bids["hospital_id"] == hid)] if not bids.empty else bids
        a3 = a[a["award_date"] >= cut3y] if not a.empty else a
        c3 = c[c["contract_date"] >= cut3y] if not c.empty else c
        amt = max(a3["award_amount"].sum() if not a3.empty else 0.0,
                  c3["contract_amount"].sum() if not c3.empty else 0.0)
        market[hid] = float(amt)
        vendors = (set(a3["winner_name"]) if not a3.empty else set()) | (set(c3["vendor_name"].dropna()) if not c3.empty else set())
        a_sorted = a.sort_values("award_date", ascending=False) if not a.empty else a
        streak = 0
        for own in (a_sorted["is_own"] if not a_sorted.empty else []):
            if own:
                break
            streak += 1
        own_recent = bool(not a_sorted.empty and a_sorted.iloc[0]["is_own"]
                          and a_sorted.iloc[0]["award_date"] >= cut1y)
        top_vendor = (a3.groupby("winner_name")["award_amount"].sum().idxmax()
                      if not a3.empty and a3["award_amount"].notna().any() else None)
        days, exp = _next_expiry(c, today)
        exp_amount = 0.0
        if exp is not None and not c.empty:
            hit = c[c["end_date"] == pd.Timestamp(exp)]
            exp_amount = float(hit["contract_amount"].fillna(0).max()) if not hit.empty else 0.0
        ob = open_bids(b, today) if not b.empty else b
        open_budget = float(ob["budget"].fillna(0).sum()) if not ob.empty else 0.0
        per[hid] = dict(
            vendors=len(vendors), streak=streak, own_recent=own_recent, has_awards=not a.empty,
            bid_count=int(b[b["bid_date"] >= cut2y]["bid_ntce_no"].nunique()) if not b.empty else 0,
            days=days, exp=exp, top_vendor=top_vendor, open_count=0 if ob.empty else len(ob),
            est=(open_budget + (exp_amount if days is not None and 0 <= days <= 180 else 0.0)),
        )
    m_scores = market_scores(market)

    out: list[Opportunity] = []
    for hid, p in per.items():
        comps = {
            "expiry": expiry_score(p["days"]),
            "market": m_scores.get(hid, 0.0),
            "competition": competition_score(p["vendors"]),
            "pattern": pattern_score(p["streak"], p["own_recent"], p["has_awards"]),
            "frequency": frequency_score(p["bid_count"]),
        }
        score = round(sum(comps[k] * w for k, w in SCORE_WEIGHTS.items()), 1)
        rebid = (p["exp"] - timedelta(days=REBID_LEAD_DAYS)) if p["exp"] else None
        o = Opportunity(
            hospital_id=hid, hospital=snap.hospital_name(hid), score=score,
            components={k: round(v, 1) for k, v in comps.items()},
            days_to_expiry=p["days"], expiry_date=p["exp"], expected_rebid=rebid,
            market_amount_3y=market[hid], est_amount=p["est"], top_vendor=p["top_vendor"],
            competitor_streak=p["streak"], open_bid_count=p["open_count"])
        o.reasons = explain(o)
        out.append(o)
    return sorted(out, key=lambda o: o.score, reverse=True)


def explain(o: Opportunity) -> list[str]:
    r: list[str] = []
    d = o.days_to_expiry
    if d is not None:
        r.append(f"계약종료 D-{d}" if d >= 0 else f"계약종료 {-d}일 경과")
    if o.components["market"] >= 75:
        r.append(f"시장규모 큼 (최근 3년 {fmt_won(o.market_amount_3y)})")
    if o.competitor_streak >= 2:
        r.append(f"최근 경쟁사 {o.competitor_streak}회 연속 수주")
    elif o.competitor_streak == 1:
        r.append("직전 입찰 경쟁사 수주")
    if o.components["competition"] >= 90:
        r.append("다수 공급사가 경합하는 시장")
    if o.open_bid_count:
        r.append(f"진행중 입찰 {o.open_bid_count}건")
    return r


def ensure_scores(repo: Repo, today: date | None = None) -> list[Opportunity]:
    """오늘자 점수를 계산해 opportunity_scores 에 upsert (같은 날 재실행해도 안전)."""
    today = today or today_kst()
    snap = load_snapshot(repo)
    opps = compute_opportunities(snap, today)
    repo.upsert("opportunity_scores", [o.to_row(today) for o in opps])
    return opps
