"""AI Next Action: 규칙 기반 추천 (항상 동작). LLM 은 문구 다듬기에만 선택적으로 사용."""
from __future__ import annotations

from dataclasses import dataclass

from .scoring import Opportunity


@dataclass
class Action:
    text: str
    urgency: str      # 긴급 | 높음 | 보통

    def __str__(self) -> str:
        return self.text


def recommend_actions(o: Opportunity) -> list[Action]:
    acts: list[Action] = []
    d = o.days_to_expiry
    if o.open_bid_count:
        acts.append(Action(f"진행중 입찰 {o.open_bid_count}건 — 입찰참가자격·제안서 제출 일정 확인", "긴급"))
    if d is not None:
        if d < 0:
            acts += [Action("종료 계약의 재입찰/수의계약 진행 여부 확인 (약제부)", "높음"),
                     Action("후속 공급사·낙찰가 정보 수집", "보통")]
        elif d <= 7:
            acts += [Action("약제부 담당자 즉시 접촉 — 재입찰 공고 일정 확인", "긴급"),
                     Action("제안자료·가격 시나리오 최종 점검", "긴급")]
        elif d <= 30:
            acts += [Action("약제부 미팅 일정 확정", "긴급"),
                     Action("제안자료 준비", "높음"),
                     Action("경쟁사 가격·납품조건 조사", "높음")]
        elif d <= 60:
            acts += [Action("약제부 미팅", "높음"), Action("경쟁사 조사", "높음"),
                     Action("제안자료 준비", "보통")]
        elif d <= 90:
            acts += [Action("약제부 미팅", "높음"), Action("경쟁사 조사", "보통"),
                     Action("제안자료 준비", "보통"), Action("KOL 미팅", "보통")]
        elif d <= 180:
            acts += [Action("약제부·KOL 관계 점검 및 사용 현황 파악", "보통")]
    if o.competitor_streak >= 2 and not (d is not None and d <= 7):
        acts.append(Action(f"경쟁사 {o.competitor_streak}회 연속 수주 — 가격/학술 차별화 포인트 정리", "높음"))
    if not acts:
        acts.append(Action("정기 방문 및 입찰 공고 모니터링 유지", "보통"))
    seen, out = set(), []
    for a in acts:                       # 중복 문구 제거, 긴급도순
        if a.text not in seen:
            seen.add(a.text)
            out.append(a)
    order = {"긴급": 0, "높음": 1, "보통": 2}
    return sorted(out, key=lambda a: order[a.urgency])
