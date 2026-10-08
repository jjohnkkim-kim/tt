"""Streamlit 로그인.

- AUTH_MODE=password (기본): 이메일로 가입 신청 → 관리자 승인 후 로그인 (hbr/auth/accounts.py)
- AUTH_MODE=entra: Microsoft Entra ID(OIDC, st.login)
- AUTH_DISABLED=true: 로그인 없이 개발용 admin 으로 진입 (운영 금지)
권한(role)·상태(status) 변경은 매 요청 DB 에서 다시 읽어 즉시 반영한다.
"""
from __future__ import annotations

import streamlit as st

from .. import branding
from ..config import get_settings
from . import accounts, persist
from .rbac import User, domain_allowed, role_for_new_user


_AUTH_CSS = """<style>
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], [data-testid="stSidebarNav"]{display:none !important;}
.block-container{max-width:480px !important; padding-top:6vh !important;}
.hbr-auth-brand{display:flex; align-items:center; gap:16px; margin-bottom:.5rem;}
.hbr-auth-brand .mk{flex:none; filter:drop-shadow(0 10px 22px rgba(37,99,235,.35));}
.hbr-auth-brand .a{font-size:.8rem; font-weight:700; letter-spacing:.28em; text-transform:uppercase; color:#1f63c2; line-height:1.2;}
.hbr-auth-brand .b{font-size:2.15rem; font-weight:800; letter-spacing:-.035em; color:#0f1b33; line-height:1.05;}
.hbr-auth-tg{font-size:.72rem; font-weight:600; letter-spacing:.14em; color:#7a889f; text-transform:uppercase; margin:.2rem 0 1.4rem;}
.hbr-auth-sub{color:#4b5a73; margin:0 0 1.2rem; font-size:.98rem;}
</style>"""


def _brand(subtitle: str = "AI 기반 병원 입찰 영업 기회 발굴 플랫폼") -> None:
    st.markdown(_AUTH_CSS + f'<div class="hbr-auth-brand"><div class="mk">{branding.mark_svg(64, "a")}</div>'
                f'<div><div class="a">Hospital</div><div class="b">Bid Radar</div></div></div>'
                f'<div class="hbr-auth-tg">{branding.TAGLINE}</div><div class="hbr-auth-sub">{subtitle}</div>', unsafe_allow_html=True)


def _login_screen(message: str | None = None) -> None:
    _brand()
    if message:
        st.error(message)
    st.button("Microsoft 계정으로 로그인", type="primary", on_click=st.login, args=("microsoft",))
    st.stop()


def require_user(repo) -> User:
    s = get_settings()
    if s.auth_disabled:
        row = repo.ensure_user("dev@local", "개발 사용자", "admin")
        return User(row["id"], row["email"], row["name"], "admin", row.get("company_id"))
    if s.auth_mode == "entra":
        return _require_entra(repo, s)
    return _require_password(repo, s)


def logout() -> None:
    if get_settings().auth_mode == "entra":
        st.logout()
    else:
        st.session_state.pop("auth_uid", None)       # on_click 콜백이 끝나면 화면이 자동으로 다시 실행된다
        st.session_state["_logged_out"] = True      # 새로고침 전까지 쿠키로 자동 로그인하지 않고, 브라우저의 쿠키를 지운다
        st.session_state["_cookie_op"] = ("clear", None)


# ── 이메일 가입 + 관리자 승인 ───────────────────────────────────
_REASONS = {
    "bad": ("error", "이메일 또는 비밀번호가 올바르지 않습니다."),
    "locked": ("error", f"로그인 시도가 너무 많습니다. {accounts.LOCK_MINUTES}분 후 다시 시도해 주세요."),
    "pending": ("warning", "관리자 승인 대기 중입니다. 승인되면 로그인할 수 있습니다."),
    "disabled": ("error", "사용할 수 없는 계정입니다. 관리자에게 문의하세요."),
}


def _secret(s) -> str:
    from ..subscribe import secret_for

    return secret_for(s)


def _flush_cookie_op() -> None:
    """로그인/로그아웃 직후 한 번만 브라우저 쿠키를 심거나 지운다 (화면에 보이지 않는 작은 스크립트)."""
    op = st.session_state.pop("_cookie_op", None)
    if op:
        import streamlit.components.v1 as components

        components.html(persist.cookie_js(op[1]), height=0)


def _cookie_user_row(repo, s) -> dict | None:
    if st.session_state.get("_logged_out"):
        return None
    try:
        token = st.context.cookies.get(persist.COOKIE)
    except Exception:   # noqa: BLE001 — 쿠키를 읽을 수 없는 환경(테스트 등)
        return None

    def lookup(uid):
        rows = repo.rows("users", [("id", "eq", uid)])
        return rows[0] if rows else None

    return persist.verify_token(_secret(s), token, lookup)


def _require_password(repo, s) -> User:
    uid = st.session_state.get("auth_uid")
    if not uid:
        row = _cookie_user_row(repo, s)
        if row:
            uid = row["id"]
            st.session_state["auth_uid"] = uid
    if uid:
        rows = repo.rows("users", [("id", "eq", uid)])
        row = rows[0] if rows else None
        if row and accounts.status_of(row) == "approved" and row.get("is_active", True):
            if row.get("must_change_password"):
                _force_change_screen(repo, row)
            _flush_cookie_op()
            return User(row["id"], row["email"], row.get("name") or row["email"], row["role"], row.get("company_id"))
        st.session_state.pop("auth_uid", None)           # 비활성화·거절된 계정은 즉시 로그아웃
        st.session_state["_cookie_op"] = ("clear", None)
    _flush_cookie_op()
    _auth_screen(repo, s)
    st.stop()


def _auth_screen(repo, s) -> None:
    _brand("로그인하거나 가입을 신청하세요")
    t_login, t_signup = st.tabs(["로그인", "가입 신청"])
    with t_login, st.form("login_form"):
        email = st.text_input("이메일", key="login_email")
        pw = st.text_input("비밀번호", type="password", key="login_password")
        if st.form_submit_button("로그인", type="primary", key="login_submit", use_container_width=True):
            res = accounts.authenticate(repo, email, pw)
            if res.ok:
                st.session_state["auth_uid"] = res.user["id"]
                st.session_state.pop("_logged_out", None)
                if _secret(s):                                    # 로그인 유지: 다음 화면에서 입장권(쿠키)을 심는다
                    st.session_state["_cookie_op"] = ("set", persist.make_token(_secret(s), res.user))
                st.rerun()
            kind, msg = _REASONS[res.reason]
            getattr(st, kind)(msg)
    with t_signup:
        st.caption("가입 신청 후 관리자가 승인하면 로그인할 수 있습니다.")
        with st.form("signup_form"):
            email = st.text_input("이메일 (로그인 ID)", key="signup_email")
            name = st.text_input("이름", key="signup_name")
            pw = st.text_input("비밀번호 (10자 이상, 영문/숫자/특수문자 중 2가지 이상)", type="password", key="signup_password")
            pw2 = st.text_input("비밀번호 확인", type="password", key="signup_password2")
            code = ""
            if s.admin_setup_code and accounts.active_admin_count(repo) == 0:      # 관리자가 아직 없을 때만 보인다
                code = st.text_input("관리자 초기 설정 코드 (최초 관리자 전용)", type="password", key="signup_code")
            if st.form_submit_button("가입 신청", type="primary", key="signup_submit", use_container_width=True):
                if pw != pw2:
                    st.error("비밀번호 확인이 일치하지 않습니다.")
                else:
                    try:
                        st.success(accounts.signup(repo, email, name, pw, s, code or None))
                    except accounts.AccountError as e:
                        st.error(str(e))


def _force_change_screen(repo, row: dict) -> None:
    _brand("비밀번호 변경")
    st.warning("임시 비밀번호로 로그인했습니다. 새 비밀번호를 설정해야 계속할 수 있습니다.")
    with st.form("force_change"):
        new = st.text_input("새 비밀번호", type="password", key="force_new")
        new2 = st.text_input("새 비밀번호 확인", type="password", key="force_new2")
        if st.form_submit_button("변경", type="primary", key="force_submit", use_container_width=True):
            if new != new2:
                st.error("비밀번호 확인이 일치하지 않습니다.")
            else:
                try:
                    accounts.change_password(repo, row["id"], None, new, require_old=False)
                    st.rerun()
                except accounts.AccountError as e:
                    st.error(str(e))
    st.button("로그아웃", on_click=lambda: st.session_state.pop("auth_uid", None))
    st.stop()


# ── Microsoft Entra ID ──────────────────────────────────────────
def _require_entra(repo, s) -> User:
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
    return User(row["id"], email, row.get("name") or name, role, row.get("company_id"))
