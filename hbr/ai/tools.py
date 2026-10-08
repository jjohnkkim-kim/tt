"""Copilot 도구: LLM 이 호출하는 *읽기 전용* 분석 함수. 수치는 항상 여기서 계산한다(LLM 은 계산하지 않음)."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from ..analytics.actions import recommend_actions
from ..analytics.data import Snapshot, open_bids, pharma_only
from ..analytics.metrics import competitor_hospitals, expiring_contracts
from ..analytics.scoring import Opportunity
from ..utils import normalize_name

TOOL_SPECS = [
    {"name": "list_expiring_contracts",
     "description": "지정한 일수 이내에 계약이 종료되는 병원/계약 목록 (D-day 오름차순).",
     "input_schema": {"type": "object", "properties": {
         "days": {"type": "integer", "description": "오늘부터 N일 이내 (기본 90)"},
         "limit": {"type": "integer"}}}},
    {"name": "top_opportunities",
     "description": "Opportunity Score 상위 병원 (점수·세부항목·근거·추천 Action 포함).",
     "input_schema": {"type": "object", "properties": {"limit": {"type": "integer"}}}},
    {"name": "visit_priorities",
     "description": "영업 방문 우선순위 추천 (점수 + 마감/계약종료 임박도 기준) 과 병원별 추천 행동.",
     "input_schema": {"type": "object", "properties": {"limit": {"type": "integer"}}}},
    {"name": "recent_bids",
     "description": "최근 N일 내 공고된 입찰, 또는 진행중 입찰. 병원 유형(대학병원 등) 필터 가능.",
     "input_schema": {"type": "object", "properties": {
         "since_days": {"type": "integer", "description": "최근 N일 공고 (기본 7)"},
         "only_open": {"type": "boolean"},
         "hospital_type": {"type": "string", "description": "예: 대학병원, 상급종합병원, 국립병원"},
         "limit": {"type": "integer"}}}},
    {"name": "important_bids",
     "description": "진행중 입찰을 예산 규모와 마감 임박도로 점수화한 가장 중요한 입찰.",
     "input_schema": {"type": "object", "properties": {"limit": {"type": "integer"}}}},
    {"name": "competitor_top_hospitals",
     "description": "특정 경쟁사(GC, CSL, JW 등)가 가장 많이 수주한 병원.",
     "input_schema": {"type": "object", "properties": {
         "competitor": {"type": "string"}, "since_days": {"type": "integer"}, "limit": {"type": "integer"}},
         "required": ["competitor"]}},
    {"name": "hospital_summary",
     "description": "특정 병원의 점수, 계약, 최근 낙찰, 진행 입찰, 추천 Action 요약.",
     "input_schema": {"type": "object", "properties": {"hospital": {"type": "string"}}, "required": ["hospital"]}},
]


def _opp_dict(o: Opportunity, with_actions: bool = True) -> dict:
    d = {"hospital": o.hospital, "score": o.score, "grade": o.grade, "components": o.components,
         "days_to_expiry": o.days_to_expiry, "expiry_date": str(o.expiry_date) if o.expiry_date else None,
         "expected_rebid": str(o.expected_rebid) if o.expected_rebid else None,
         "est_amount_won": o.est_amount, "reasons": o.reasons}
    if with_actions:
        d["actions"] = [a.text for a in recommend_actions(o)[:4]]
    return d


class ToolRunner:
    def __init__(self, snap: Snapshot, opps: list[Opportunity], today: date):
        self.snap, self.opps, self.today = snap, opps, today

    def run(self, name: str, args: dict) -> dict:
        fn = getattr(self, f"_{name}", None)
        if fn is None:
            return {"error": f"unknown tool {name}"}
        try:
            return fn(**(args or {}))
        except TypeError as e:
            return {"error": f"bad arguments: {e}"}

    # ── tools
    def _list_expiring_contracts(self, days: int = 90, limit: int = 20) -> dict:
        df = expiring_contracts(self.snap, self.today, days)
        rows = [{"hospital": r.hospital, "title": r.title, "vendor": r.vendor_name, "amount_won": r.contract_amount,
                 "end_date": str(r.end_date.date()), "d_day": int(r.d_day), "end_date_estimated": bool(r.end_date_estimated)}
                for r in df.head(limit).itertuples()]
        return {"days": days, "count": len(df), "contracts": rows}

    def _top_opportunities(self, limit: int = 10) -> dict:
        return {"opportunities": [_opp_dict(o) for o in self.opps[:limit]]}

    def _visit_priorities(self, limit: int = 5) -> dict:
        def urgency(o: Opportunity) -> float:
            bonus = 0.0
            if o.days_to_expiry is not None and 0 <= o.days_to_expiry <= 30:
                bonus += 10
            if o.open_bid_count:
                bonus += 5
            return o.score + bonus
        ranked = sorted(self.opps, key=urgency, reverse=True)[:limit]
        return {"priorities": [_opp_dict(o) for o in ranked]}

    def _recent_bids(self, since_days: int = 7, only_open: bool = False, hospital_type: str | None = None,
                     limit: int = 20) -> dict:
        bids = pharma_only(self.snap.bids)
        if bids.empty:
            return {"count": 0, "bids": []}
        if only_open:
            bids = open_bids(bids, self.today)
        else:
            bids = bids[bids["bid_date"] >= pd.Timestamp(self.today - timedelta(days=since_days))]
        if hospital_type:
            pat = "대학병원|상급종합" if "대학" in hospital_type else hospital_type   # 상급종합은 대부분 대학병원
            ids = set(self.snap.hospitals[self.snap.hospitals["hospital_type"].str.contains(pat, na=False)]["id"])
            bids = bids[bids["hospital_id"].isin(ids)]
        bids = bids.sort_values("bid_date", ascending=False)
        return {"count": len(bids), "bids": [
            {"hospital": b.hospital, "title": b.title, "budget_won": b.budget, "bid_date": str(b.bid_date.date()),
             "deadline": str(b.deadline) if pd.notna(b.deadline) else None} for b in bids.head(limit).itertuples()]}

    def _important_bids(self, limit: int = 5) -> dict:
        ob = open_bids(pharma_only(self.snap.bids), self.today)
        if ob.empty:
            return {"bids": []}
        days = ((ob["deadline"] - pd.Timestamp(self.today)).dt.days).fillna(30).clip(lower=0)
        ob = ob.assign(priority=ob["budget"].fillna(0) / 1e8 * (1 + (14 - days).clip(lower=0) / 14))
        ob = ob.sort_values("priority", ascending=False).head(limit)
        return {"bids": [{"hospital": b.hospital, "title": b.title, "budget_won": b.budget,
                          "deadline": str(b.deadline) if pd.notna(b.deadline) else None} for b in ob.itertuples()]}

    def _competitor_top_hospitals(self, competitor: str, since_days: int | None = None, limit: int = 10) -> dict:
        since = self.today - timedelta(days=since_days) if since_days else None
        df = competitor_hospitals(self.snap, competitor, since)
        return {"competitor": competitor, "hospitals": [
            {"hospital": r.hospital, "awards": int(r.count), "amount_won": r.amount, "last_award": str(r.last.date())}
            for r in df.head(limit).itertuples()]}

    def _hospital_summary(self, hospital: str) -> dict:
        h = self.snap.hospitals
        n = normalize_name(hospital)
        hit = h[h["name_norm"].str.contains(n, na=False, regex=False)] if n else h.iloc[0:0]
        if hit.empty:
            return {"error": f"'{hospital}' 병원을 찾지 못했습니다"}
        hid, name = int(hit.iloc[0]["id"]), hit.iloc[0]["name"]
        opp = next((o for o in self.opps if o.hospital_id == hid), None)
        aw = pharma_only(self.snap.awards)
        aw = aw[aw["hospital_id"] == hid].sort_values("award_date", ascending=False).head(5) if not aw.empty else aw
        con = pharma_only(self.snap.contracts)
        con = con[con["hospital_id"] == hid].sort_values("end_date", ascending=False).head(5) if not con.empty else con
        return {"hospital": name,
                "opportunity": _opp_dict(opp) if opp else None,
                "recent_awards": [{"winner": a.winner_name, "amount_won": a.award_amount, "date": str(a.award_date.date())}
                                  for a in aw.itertuples()] if not aw.empty else [],
                "contracts": [{"vendor": c.vendor_name, "amount_won": c.contract_amount, "end_date": str(c.end_date.date())}
                              for c in con.itertuples()] if not con.empty else []}
