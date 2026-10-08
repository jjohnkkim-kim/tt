"""이메일 가입 + 관리자 승인 로그인 화면(AppTest) 통합 테스트."""
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from hbr.auth import passwords
from hbr.auth.rbac import User

ROOT = Path(__file__).resolve().parents[1]
PW = "Correct-horse-9"


@pytest.fixture(autouse=True)
def password_mode(monkeypatch):
    monkeypatch.setattr(passwords, "ITERATIONS", 1000)
    monkeypatch.setenv("AUTH_DISABLED", "false")
    monkeypatch.setenv("AUTH_MODE", "password")
    monkeypatch.setenv("ADMIN_SETUP_CODE", "SETUP-CODE")
    monkeypatch.setenv("ALLOWED_EMAIL_DOMAINS", "")
    st.cache_resource.clear()
    yield
    st.cache_resource.clear()


def app() -> AppTest:
    return AppTest.from_file(str(ROOT / "app.py"), default_timeout=90).run()


def signup(at, email, name, pw=PW, code=""):
    at.text_input(key="signup_email").set_value(email)
    at.text_input(key="signup_name").set_value(name)
    at.text_input(key="signup_password").set_value(pw)
    at.text_input(key="signup_password2").set_value(pw)
    if code:
        at.text_input(key="signup_code").set_value(code)
    at.button(key="signup_submit").click().run()


def login(at, email, pw=PW):
    at.text_input(key="login_email").set_value(email)
    at.text_input(key="login_password").set_value(pw)
    at.button(key="login_submit").click().run()


def test_unauthenticated_user_sees_only_login_screen():
    at = app()
    assert not at.exception and any("Hospital Bid Radar" in m.value for m in at.markdown)
    assert len(at.metric) == 0                                    # 데이터(KPI) 노출 없음
    assert at.text_input(key="login_email") and at.text_input(key="signup_email")
    assert not any("Dashboard" in str(m.value) for m in at.markdown)


def test_full_flow_signup_pending_approval_login_revocation():
    at = app()
    signup(at, "boss@corp.com", "대표", code="SETUP-CODE")        # 최초 관리자 (코드)
    assert not at.exception and any("접수" in s.value for s in at.success)
    boss = app()
    login(boss, "boss@corp.com")
    assert not boss.exception and len(boss.metric) >= 4 and any(">admin<" in m.value for m in boss.sidebar.markdown)

    user_page = app()
    signup(user_page, "sales@gmail.com", "김영업")                 # 일반 가입 → 대기
    pending = app()
    login(pending, "sales@gmail.com")
    assert any("승인 대기" in w.value for w in pending.warning) and len(pending.metric) == 0

    from views._common import repo
    r = repo()
    admin = r.get_user("boss@corp.com")
    adm_page = AppTest.from_file(str(ROOT / "views/settings.py"), default_timeout=90)
    adm_page.session_state["user"] = User(admin["id"], admin["email"], "대표", "admin")
    adm_page.run()
    assert not adm_page.exception
    sid = r.get_user("sales@gmail.com")["id"]
    adm_page.selectbox(key=f"role_{sid}").select("sales")
    adm_page.button(key=f"ok_{sid}").click().run()
    assert r.get_user("sales@gmail.com")["status"] == "approved" and r.get_user("sales@gmail.com")["role"] == "sales"

    ok = app()
    login(ok, "sales@gmail.com")
    assert len(ok.metric) >= 4 and any(">sales<" in m.value for m in ok.sidebar.markdown)

    r.update("users", {"is_active": False}, [("id", "eq", sid)])   # 관리자가 비활성화 → 다음 요청에서 즉시 로그아웃
    ok.run()
    assert len(ok.metric) == 0 and ok.text_input(key="login_email")


def test_signup_form_errors_and_no_account_enumeration():
    at = app()
    signup(at, "a@gmail.com", "A", pw="short")
    assert any("10자" in e.value for e in at.error)
    at = app()
    at.text_input(key="signup_email").set_value("a@gmail.com")
    at.text_input(key="signup_name").set_value("A")
    at.text_input(key="signup_password").set_value(PW)
    at.text_input(key="signup_password2").set_value(PW + "x")
    at.button(key="signup_submit").click().run()
    assert any("일치하지" in e.value for e in at.error)
    at = app()
    signup(at, "dup@gmail.com", "A")
    first = [s.value for s in at.success]
    at = app()
    signup(at, "dup@gmail.com", "B")
    assert [s.value for s in at.success] == first                     # 중복 가입도 같은 문구


def test_wrong_password_message_is_generic():
    at = app()
    signup(at, "a@gmail.com", "A")
    at = app()
    login(at, "a@gmail.com", "wrong-password-1")
    at2 = app()
    login(at2, "ghost@gmail.com", "wrong-password-1")
    assert [e.value for e in at.error] == [e.value for e in at2.error] and at.error


def test_temp_password_forces_change_before_access():
    from hbr.auth import accounts
    at = app()
    signup(at, "boss@corp.com", "대표", code="SETUP-CODE")
    from views._common import repo
    r = repo()
    temp = accounts.reset_password(r, r.get_user("boss@corp.com")["id"])
    forced = app()
    login(forced, "boss@corp.com", temp)
    assert len(forced.metric) == 0 and forced.text_input(key="force_new")          # 변경 전에는 앱 사용 불가
    forced.text_input(key="force_new").set_value("Brand-new-pass-5")
    forced.text_input(key="force_new2").set_value("Brand-new-pass-5")
    forced.button(key="force_submit").click().run()
    assert not forced.exception and len(forced.metric) >= 4


def test_auth_disabled_still_works(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "true")
    st.cache_resource.clear()
    at = app()
    assert not at.exception and len(at.metric) >= 4


def test_setup_code_field_is_hidden_once_an_admin_exists():
    at = app()
    assert at.text_input(key="signup_code")                       # 관리자가 없으면 보인다
    signup(at, "boss@corp.com", "대표", code="SETUP-CODE")
    later = app()
    assert not [t for t in later.text_input if t.key == "signup_code"]
