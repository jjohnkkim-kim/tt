"""요금제와 사용 한도. 결제 연동 전이라 플랜은 관리자가 회사별로 지정한다. 가격은 정해지지 않아 여기에 넣지 않는다."""
from __future__ import annotations

from datetime import date

PLANS = {
    "free": {"label": "Free", "products": 3, "seats": 2},
    "pro": {"label": "Pro", "products": 30, "seats": 10},
    "team": {"label": "Team", "products": 200, "seats": 50},
}
PLAN_ORDER = list(PLANS)


class PlanLimitError(ValueError):
    pass


def plan_of(company: dict | None, today: date | None = None) -> str:
    """회사의 현재 플랜. plan 컬럼이 없거나(마이그레이션 전) 기한이 지났으면 free."""
    if not company:
        return "free"
    plan = company.get("plan") if company.get("plan") in PLANS else "free"
    until = company.get("plan_until")
    if until and plan != "free":
        until = date.fromisoformat(str(until)[:10])
        if until < (today or date.today()):
            return "free"
    return plan


def limit(company: dict | None, key: str, today: date | None = None) -> int:
    return PLANS[plan_of(company, today)][key]


def check_can_add(company: dict | None, key: str, used: int, today: date | None = None) -> None:
    """key: 'products' | 'seats'. 한도에 이미 닿았으면 PlanLimitError."""
    cap = limit(company, key, today)
    if used >= cap:
        name = {"products": "관심 제품", "seats": "팀원"}[key]
        raise PlanLimitError(f"현재 요금제({PLANS[plan_of(company, today)]['label']})는 {name}을 {cap}개(명)까지 쓸 수 있어요. "
                             "더 쓰려면 관리자에게 요금제 변경을 요청하세요.")
