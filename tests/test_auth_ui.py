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
    at.text_input(key="signup_code").set_value(code)
    at.button(key="signup_submit").click().run()


def login(at, email, pw=PW):
    at.text_input(key="login_email").set_value(email)
    at.text_input(key="login_password").set_value(pw)
    at.button(key="login_submit").click().run()


def test_unauthenticated_user_sees_only_login_screen():
    at = app()
    assert not at.exception and "Hospital Bid Radar" in at.title[0].value
    assert len(at.metric) == 0                                    # 데이터(KPI) 노출 없음
    assert at.text_input(key="login_email") and at.text_input(key="signup_email")
    assert not any("Dashboard" in str(m.value) for m in at.markdown)


def test_full_flow_signup_pending_approval_login_revocation():
    at = app()
    signup(at, "boss@corp.com", "대표", code="SETUP-CODE")        # 최초 관리자 (코드)
    assert not at.exception and any("관리자 계정이 준비" in s.value for s in at.success)
    boss = app()
    login(boss, "boss@corp.com")
    assert not boss.exception and len(boss.metric) >= 6 and boss.sidebar.markdown[0].value.endswith("`admin`")

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
    assert len(ok.metric) >= 6 and ok.sidebar.markdown[0].value.endswith("`sales`")

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
    assert not forced.exception and len(forced.metric) >= 6


def test_auth_disabled_still_works(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "true")
    st.cache_resource.clear()
    at = app()
    assert not at.exception and len(at.metric) >= 6


def test_login_screen_shows_demo_storage_warning():
    at = app()
    assert any("데모 모드" in w.value and "저장되지 않" in w.value for w in at.warning)


def test_pending_account_promoted_by_setup_code_with_same_password():
    """실제 사례: 코드 없이 먼저 가입(대기) → 같은 이메일·비밀번호 + 코드로 다시 가입하면 최초 관리자로 승격."""
    at = app()
    signup(at, "j@corp.com", "김관리")                            # 코드 없이 가입 → 대기
    at = app()
    login(at, "j@corp.com")
    assert any("승인 대기" in w.value for w in at.warning)
    at = app()
    signup(at, "j@corp.com", "김관리", code="SETUP-CODE")          # 같은 계정 + 코드
    assert any("관리자 계정이 준비" in s.value for s in at.success)
    at = app()
    login(at, "j@corp.com")
    assert len(at.metric) >= 6 and at.sidebar.markdown[0].value.endswith("`admin`")


def test_repo_rebuilt_when_storage_settings_change(monkeypatch):
    from views._common import repo
    first = repo()
    assert repo() is first                                          # 같은 설정이면 재사용
    monkeypatch.setenv("SUPABASE_URL", "https://abc.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_x")
    monkeypatch.setenv("DATA_BACKEND", "memory")                    # 키 해시는 바뀌지만 메모리로 강제(접속 없이 검증)
    assert repo() is not first                                      # 설정이 바뀌면 새 연결
