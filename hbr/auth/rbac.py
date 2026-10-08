"""RBAC: 역할 계층(viewer < sales < manager < admin) 과 기능별 최소 권한."""
from __future__ import annotations

from dataclasses import dataclass

from ..constants import ROLES

# 기능(페이지/동작) → 필요한 최소 역할
REQUIRED_ROLE = {
    "dashboard": "viewer", "bids": "viewer", "awards": "viewer", "contracts": "viewer", "hospital": "viewer",
    "competitors": "sales", "copilot": "sales",
    "download": "sales",            # 데이터 반출은 영업 이상만
    "watchlist": "sales",
    "product_edit": "sales",        # 회사의 관심 제품 등록·수정
    "company_edit": "manager",      # 회사 정보·자사 표기명 수정
    "team": "manager",
    "admin": "admin",
}


@dataclass(frozen=True)
class User:
    id: int | None
    email: str
    name: str
    role: str
    company_id: int | None = None          # 소속 회사 (회사별 데이터는 이 값으로만 구분한다)

    def can(self, feature: str) -> bool:
        need = REQUIRED_ROLE.get(feature, "admin")        # 정의되지 않은 기능은 admin 전용 (deny by default)
        return ROLES.index(self.role) >= ROLES.index(need) if self.role in ROLES else False


def role_for_new_user(email: str, admin_emails: list[str]) -> str:
    return "admin" if email.lower() in admin_emails else "viewer"


def domain_allowed(email: str, allowed_domains: list[str]) -> bool:
    if not allowed_domains:
        return True
    return email.lower().rsplit("@", 1)[-1] in allowed_domains
