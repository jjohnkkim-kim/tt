"""Streamlit 로그인: Microsoft Entra ID(OIDC, st.login) + 사용자 DB 연동 + RBAC.

AUTH_DISABLED=true 이면 로그인 없이 로컬 개발용 admin 으로 진입한다 (운영 금지).
"""
from __future__ import annotations

import streamlit as st

from ..config import get_settings
from .rbac import User, domain_allowed, role_for_new_user


def _login_screen(message: str | None = None) -> None:
    st.title("🏥 Hospital Bid Radar")
    st.caption("AI 기반 병원 입찰 영업 기회 발굴 플랫폼")
    if message:
        st.error(message)
    st.button("Microsoft 계정으로 로그인", type="primary", on_click=st.login, args=("microsoft",))
    st.stop()


def require_user(repo) -> User:
    s = get_settings()
    if s.auth_disabled:
        row = repo.ensure_user("dev@local", "개발 사용자", "admin")
        return User(row["id"], row["email"], row["name"], "admin")

    if not getattr(st.user, "is_logged_in", False):
        _login_screen()
    email = (st.user.get("email") or st.user.get("preferred_username") or "").lower()
    name = st.user.get("name") or email
    if not email:
        _login_screen("계정에서 이메일을 확인할 수 없습니다. 관리자에게 문의하세요.")
    if not domain_allowed(email, s.allowed_email_domains):
        st.error(f"{email} 은(는) 허용된 도메인이 아닙니다.")
        st.button("로그아웃", on_click=st.logout)
        st.stop()

    row = repo.get_user(email)
    if row is None:
        if not s.auto_provision and email not in s.admin_emails:
            st.warning("등록되지 않은 사용자입니다. 관리자에게 접근 권한을 요청하세요.")
            st.button("로그아웃", on_click=st.logout)
            st.stop()
        row = repo.ensure_user(email, name, role_for_new_user(email, s.admin_emails))
    if not row.get("is_active", True):
        st.error("비활성화된 계정입니다.")
        st.stop()
    # ADMIN_EMAILS 에 있으면 항상 admin (부트스트랩/복구용)
    role = "admin" if email in s.admin_emails else row["role"]
    return User(row["id"], email, row.get("name") or name, role)
