"""사용자별 알림 조건: 어떤 종류·범위의 알림을 받을지 판단한다 (이벤트는 공통, '누구에게 보일지'만 사용자 조건으로 거른다).

범위 scope
- all : 모든 병원·제품의 알림
- mine: 내 관심 제품에 매칭(최소 신뢰도 이상)되거나, 내 관심 병원에서 난 알림
회사별 정보(제품·자사 표기명)는 항상 그 사용자의 회사 것만 쓴다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..collectors.competitors import matches_any_alias
from ..constants import DEADLINE_DAYS, RULE_TYPES
from .matching import match_text

FLOORS = {"HIGH": 80, "MEDIUM": 55, "LOW": 35}


@dataclass(frozen=True)
class Rule:
    types: tuple[str, ...] = tuple(RULE_TYPES)
    deadline_days: tuple[int, ...] = DEADLINE_DAYS
    scope: str = "all"
    min_match: str = "MEDIUM"
    exclude_own: bool = True
    email_enabled: bool = True


@dataclass
class Context:
    """한 사용자의 판단 재료. 모두 그 사용자의 회사·계정 것만 담긴다."""
    products: list[dict] = field(default_factory=list)
    own_aliases: list[str] = field(default_factory=list)
    watched: set[int] = field(default_factory=set)


DEFAULT_RULE = Rule()


def rule_from_row(row: dict | None) -> Rule:
    if not row:
        return DEFAULT_RULE
    return Rule(types=tuple(t for t in (row.get("types") or []) if t in RULE_TYPES),
                deadline_days=tuple(sorted({int(d) for d in (row.get("deadline_days") or [])}, reverse=True)),
                scope=row.get("scope") if row.get("scope") in ("all", "mine") else "all",
                min_match=row.get("min_match") if row.get("min_match") in FLOORS else "MEDIUM",
                exclude_own=bool(row.get("exclude_own", True)), email_enabled=bool(row.get("email_enabled", True)))


def rule_to_row(rule: Rule) -> dict:
    return {"types": list(rule.types), "deadline_days": list(rule.deadline_days), "scope": rule.scope, "min_match": rule.min_match,
            "exclude_own": rule.exclude_own, "email_enabled": rule.email_enabled}


def _kind(alert: dict) -> str:
    """예전 '경쟁사 수주' 기록은 '낙찰 결과'로 본다."""
    return "AWARD" if alert.get("alert_type") == "COMPETITOR_AWARD" else alert.get("alert_type")


def alert_text(alert: dict) -> str:
    payload = alert.get("payload") or {}
    if payload.get("title"):
        return str(payload["title"])
    t = str(alert.get("title") or "")
    return t.split(" — ", 1)[-1]               # 예전 기록: '병원 — 제목' 에서 제목 부분


def alert_winner(alert: dict) -> str:
    payload = alert.get("payload") or {}
    return str(payload.get("winner") or str(alert.get("title") or "").split(" — ")[0])


def alert_matches(rule: Rule, alert: dict, ctx: Context) -> bool:
    """이 사용자(조건 rule, 재료 ctx)에게 이 알림을 보여줄지."""
    kind = _kind(alert)
    if kind not in rule.types:
        return False
    payload = alert.get("payload") or {}
    if kind == "DEADLINE" and int(payload.get("days") or 0) not in rule.deadline_days:
        return False
    if kind == "AWARD" and rule.exclude_own and matches_any_alias(alert_winner(alert), ctx.own_aliases):
        return False
    if rule.scope == "all":
        return True
    floor = FLOORS[rule.min_match]
    tags = payload.get("tags") or ()
    product_hit = any(m.score >= floor for m in match_text(ctx.products, alert_text(alert), tags)) if ctx.products else False
    hospital_hit = alert.get("hospital_id") in ctx.watched if alert.get("hospital_id") is not None else False
    return product_hit or hospital_hit


def context_for(repo, user: dict) -> Context:
    cid = user.get("company_id")
    return Context(products=repo.list_products(cid), own_aliases=repo.own_aliases(cid), watched=set(repo.watched_hospital_ids(user["id"])))


def visible_alerts(repo, user: dict, days: int = 30, limit: int = 300) -> list[dict]:
    """앱 안의 '알림' 화면용: 최근 N일 알림 중 이 사용자 조건에 맞는 것 (조건이 없으면 전체 범위 기본 조건)."""
    from datetime import datetime, timedelta, timezone

    rule = rule_from_row(repo.get_alert_rule(user["id"]))
    ctx = context_for(repo, user)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = [a for a in repo.rows("alerts", order="-id", limit=2000) if str(a.get("created_at") or "") >= since[:19]]
    return [a for a in rows if alert_matches(rule, a, ctx)][:limit]
