"""팀 관리: 매니저가 자기 회사 팀원의 역할·사용 여부를 바꾼다. 관리자 권한을 주거나 다른 회사 사람은 건드릴 수 없다."""
from __future__ import annotations

from .auth import accounts
from .auth.rbac import User
from .constants import ROLES

TEAM_ROLES = [r for r in ROLES if r != "admin"]          # 매니저가 부여할 수 있는 역할


class TeamError(ValueError):
    pass


def set_member(repo, actor: User, target_id: int, *, role: str | None = None, is_active: bool | None = None) -> None:
    if not actor.can("team") or not actor.company_id:
        raise TeamError("팀 관리는 소속 회사가 있는 매니저 이상만 할 수 있어요.")
    target = next((u for u in repo.company_members(actor.company_id) if u["id"] == target_id), None)
    if not target:
        raise TeamError("우리 회사 팀원이 아니에요.")
    if target["id"] == actor.id:
        raise TeamError("내 계정은 여기서 바꿀 수 없어요.")
    if target.get("role") == "admin" and actor.role != "admin":
        raise TeamError("관리자 계정은 관리자만 바꿀 수 있어요.")
    if role is not None and actor.role != "admin" and role not in TEAM_ROLES:
        raise TeamError("관리자 역할은 줄 수 없어요.")
    try:
        accounts.update_user(repo, target_id, role=role, is_active=is_active)
    except accounts.AccountError as e:
        raise TeamError(str(e)) from e
