import time
from datetime import datetime, timedelta, timezone

import pytest

from hbr.auth import accounts, passwords
from hbr.auth.accounts import AccountError, authenticate, signup
from hbr.config import get_settings


@pytest.fixture(autouse=True)
def fast_hash(monkeypatch):
    monkeypatch.setattr(passwords, "ITERATIONS", 1000)       # 테스트 속도용


def settings(**kw):
    s = get_settings()
    return s.__class__(**{**s.__dict__, "admin_setup_code": "", "allowed_email_domains": [], **kw})


PW = "Correct-horse-9"


# ── 비밀번호 ────────────────────────────────────────────────────
def test_hash_verify_roundtrip_and_salt():
    h1, h2 = passwords.hash_password(PW), passwords.hash_password(PW)
    assert h1 != h2 and passwords.verify_password(PW, h1) and not passwords.verify_password(PW + "x", h1)
    assert PW not in h1


@pytest.mark.parametrize("bad", [None, "", "plain", "pbkdf2_sha256$x$y$z", "md5$1$a$b", "a$b$c$d$e"])
def test_verify_never_raises_on_garbage(bad):
    assert passwords.verify_password(PW, bad) is False


@pytest.mark.parametrize("pw,ok", [
    ("short1!", False), ("abcdefghijkl", False), ("1234567890", False), ("Password1234", False),
    ("a" * 129 + "1", False), ("aaaaaaaaaa1", False), ("Correct-horse-9", True), ("한글비밀번호1234!", True)])
def test_password_policy(pw, ok):
    assert (passwords.password_problem(pw, "kim@x.com") is None) is ok


def test_password_cannot_contain_email_id():
    assert passwords.password_problem("kimjonggyun-99!", "kimjonggyun@x.com")
    assert passwords.password_problem("Correct-horse-9", "kimjonggyun@x.com") is None


def test_temp_password_meets_policy():
    for _ in range(20):
        assert passwords.password_problem(passwords.generate_temp_password()) is None


# ── 가입 → 승인 → 로그인 ─────────────────────────────────────────
def test_signup_creates_pending_viewer_and_cannot_login_until_approved(repo):
    msg = signup(repo, "  Kim@Gmail.com ", "김영업", PW, settings())
    u = repo.get_user("kim@gmail.com")
    assert msg == accounts.RECEIVED and u["status"] == "pending" and u["role"] == "viewer"
    assert u["password_hash"] and PW not in str(u)
    res = authenticate(repo, "KIM@gmail.com", PW)
    assert not res.ok and res.reason == "pending"
    accounts.approve(repo, u["id"], "sales", admin_id=None)
    res = authenticate(repo, "kim@gmail.com", PW)
    assert res.ok and res.user["role"] == "sales"
    assert repo.get_user("kim@gmail.com")["last_login_at"]


def test_wrong_password_and_unknown_user_look_identical(repo):
    signup(repo, "a@x.com", "A", PW, settings())
    r1, r2 = authenticate(repo, "a@x.com", "wrong-password-1"), authenticate(repo, "nobody@x.com", "wrong-password-1")
    assert (r1.ok, r1.reason) == (r2.ok, r2.reason) == (False, "bad")
    assert authenticate(repo, "", "x").reason == "bad"


def test_pending_status_not_revealed_without_correct_password(repo):
    signup(repo, "a@x.com", "A", PW, settings())
    assert authenticate(repo, "a@x.com", "wrong-password-1").reason == "bad"      # 대기 중인지 알 수 없음


def test_duplicate_signup_is_silent_and_does_not_overwrite(repo):
    signup(repo, "a@x.com", "A", PW, settings())
    u = repo.get_user("a@x.com")
    accounts.approve(repo, u["id"], "sales", None)
    msg = signup(repo, "a@x.com", "Hacker", "Another-pass-77", settings())          # 같은 문구, 변경 없음
    assert msg == accounts.RECEIVED
    again = repo.get_user("a@x.com")
    assert again["name"] == "A" and again["role"] == "sales" and again["status"] == "approved"
    assert authenticate(repo, "a@x.com", PW).ok and not authenticate(repo, "a@x.com", "Another-pass-77").ok


@pytest.mark.parametrize("email,name,pw,msg", [
    ("not-an-email", "A", PW, "이메일"), ("a@x.com", "", PW, "이름"), ("a@x.com", "x" * 51, PW, "이름"),
    ("a@x.com", "A", "short", "10자")])
def test_signup_validation(repo, email, name, pw, msg):
    with pytest.raises(AccountError, match=msg):
        signup(repo, email, name, pw, settings())
    assert repo.rows("users") == []


def test_domain_restriction(repo):
    s = settings(allowed_email_domains=["corp.com"])
    with pytest.raises(AccountError, match="도메인"):
        signup(repo, "a@gmail.com", "A", PW, s)
    signup(repo, "a@corp.com", "A", PW, s)
    assert repo.get_user("a@corp.com")


def test_rejected_and_disabled_cannot_login(repo):
    signup(repo, "a@x.com", "A", PW, settings())
    uid = repo.get_user("a@x.com")["id"]
    accounts.approve(repo, uid, "admin", None)
    signup(repo, "b@x.com", "B", PW, settings())
    bid = repo.get_user("b@x.com")["id"]
    accounts.reject(repo, bid)
    assert authenticate(repo, "b@x.com", PW).reason == "disabled"
    accounts.approve(repo, bid, "sales", uid)
    assert authenticate(repo, "b@x.com", PW).ok
    accounts.update_user(repo, bid, is_active=False)
    assert authenticate(repo, "b@x.com", PW).reason == "disabled"


# ── 잠금 ─────────────────────────────────────────────────────────
def test_lockout_after_repeated_failures_even_with_correct_password(repo):
    signup(repo, "a@x.com", "A", PW, settings())
    accounts.approve(repo, repo.get_user("a@x.com")["id"], "sales", None)
    for _ in range(accounts.MAX_FAILS):
        assert authenticate(repo, "a@x.com", "wrong-password-1").reason == "bad"
    assert authenticate(repo, "a@x.com", PW).reason == "locked"                    # 올바른 비밀번호도 잠금 중엔 거부
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    repo.update("users", {"locked_until": past}, [("email", "eq", "a@x.com")])
    assert authenticate(repo, "a@x.com", PW).ok                                      # 잠금 해제 후 성공, 실패 횟수 초기화
    assert repo.get_user("a@x.com")["failed_attempts"] == 0


def test_success_resets_failed_attempts(repo):
    signup(repo, "a@x.com", "A", PW, settings())
    accounts.approve(repo, repo.get_user("a@x.com")["id"], "sales", None)
    for _ in range(accounts.MAX_FAILS - 1):
        authenticate(repo, "a@x.com", "wrong-password-1")
    assert authenticate(repo, "a@x.com", PW).ok and repo.get_user("a@x.com")["failed_attempts"] == 0
    for _ in range(accounts.MAX_FAILS - 1):
        authenticate(repo, "a@x.com", "wrong-password-1")
    assert authenticate(repo, "a@x.com", PW).ok                                     # 누적되지 않아 잠기지 않음


# ── 최초 관리자 코드 ─────────────────────────────────────────────
def test_setup_code_creates_first_admin_only_when_no_admin_exists(repo):
    s = settings(admin_setup_code="SETUP-123")
    signup(repo, "boss@x.com", "대표", PW, s, setup_code="SETUP-123")
    boss = repo.get_user("boss@x.com")
    assert boss["role"] == "admin" and boss["status"] == "approved"
    assert authenticate(repo, "boss@x.com", PW).ok
    signup(repo, "evil@x.com", "공격자", PW, s, setup_code="SETUP-123")             # 관리자가 이미 있으면 코드 무효
    evil = repo.get_user("evil@x.com")
    assert evil["role"] == "viewer" and evil["status"] == "pending"


def test_wrong_or_missing_setup_code_never_makes_admin(repo):
    s = settings(admin_setup_code="SETUP-123")
    for code in (None, "", "setup-123", "SETUP-124", " "):
        signup(repo, f"u{abs(hash(code))}@x.com", "U", PW, s, setup_code=code)
    assert all(u["role"] == "viewer" and u["status"] == "pending" for u in repo.rows("users"))
    signup(repo, "u@x.com", "U", PW, settings(admin_setup_code=""), setup_code="anything")     # 코드 미설정 시 비활성
    assert repo.get_user("u@x.com")["role"] == "viewer"


# ── 관리자 보호 ──────────────────────────────────────────────────
def _admin(repo, email="boss@x.com"):
    signup(repo, email, "관리자", PW, settings(admin_setup_code="C"), setup_code="C")
    return repo.get_user(email)["id"]


def test_last_admin_cannot_be_demoted_disabled_or_rejected(repo):
    a = _admin(repo)
    for kw in ({"role": "sales"}, {"is_active": False}):
        with pytest.raises(AccountError, match="마지막 관리자"):
            accounts.update_user(repo, a, **kw)
    with pytest.raises(AccountError, match="마지막 관리자"):
        accounts.reject(repo, a)
    signup(repo, "b@x.com", "B", PW, settings())
    b = repo.get_user("b@x.com")["id"]
    accounts.approve(repo, b, "admin", a)
    accounts.update_user(repo, a, role="sales")                                       # 관리자가 둘이면 강등 가능
    with pytest.raises(AccountError, match="마지막 관리자"):
        accounts.update_user(repo, b, role="viewer")


def test_unknown_role_rejected(repo):
    a = _admin(repo)
    with pytest.raises(AccountError):
        accounts.approve(repo, a, "superuser", None)
    with pytest.raises(AccountError):
        accounts.update_user(repo, a, role="root")


# ── 비밀번호 초기화/변경 ─────────────────────────────────────────
def test_reset_forces_change_and_old_password_stops_working(repo):
    a = _admin(repo)
    signup(repo, "u@x.com", "U", PW, settings())
    uid = repo.get_user("u@x.com")["id"]
    accounts.approve(repo, uid, "sales", a)
    temp = accounts.reset_password(repo, uid)
    assert not authenticate(repo, "u@x.com", PW).ok
    res = authenticate(repo, "u@x.com", temp)
    assert res.ok and res.user["must_change_password"] is True
    accounts.change_password(repo, uid, None, "Brand-new-pass-5", require_old=False)
    assert authenticate(repo, "u@x.com", "Brand-new-pass-5").ok and not authenticate(repo, "u@x.com", temp).ok
    assert repo.get_user("u@x.com")["must_change_password"] is False


def test_change_password_checks(repo):
    a = _admin(repo)
    with pytest.raises(AccountError, match="현재 비밀번호"):
        accounts.change_password(repo, a, "wrong", "Brand-new-pass-5")
    with pytest.raises(AccountError, match="10자"):
        accounts.change_password(repo, a, PW, "short")
    with pytest.raises(AccountError, match="다른 비밀번호"):
        accounts.change_password(repo, a, PW, PW)
    accounts.change_password(repo, a, PW, "Brand-new-pass-5")
    assert authenticate(repo, "boss@x.com", "Brand-new-pass-5").ok


def test_reset_clears_lock(repo):
    a = _admin(repo)
    for _ in range(accounts.MAX_FAILS):
        authenticate(repo, "boss@x.com", "wrong-password-1")
    assert authenticate(repo, "boss@x.com", PW).reason == "locked"
    temp = accounts.reset_password(repo, a)
    assert authenticate(repo, "boss@x.com", temp).ok


def test_users_without_password_hash_cannot_password_login(repo):
    repo.ensure_user("ms@corp.com", "MS 사용자", "sales")                  # Microsoft 로그인으로 만들어진 계정
    assert authenticate(repo, "ms@corp.com", PW).reason == "bad"
    assert authenticate(repo, "ms@corp.com", "").reason == "bad"


# ── 먼저 일반 가입한 계정의 최초 관리자 승격 ─────────────────────
def test_existing_pending_account_promoted_with_code_and_correct_password(repo):
    s = settings(admin_setup_code="SETUP-123")
    assert signup(repo, "j@corp.com", "김", PW, s) == accounts.RECEIVED            # 코드 없이 가입 → 대기
    assert repo.get_user("j@corp.com")["status"] == "pending"
    assert signup(repo, "j@corp.com", "김", PW, s, setup_code="SETUP-123") == accounts.ADMIN_READY
    u = repo.get_user("j@corp.com")
    assert u["role"] == "admin" and u["status"] == "approved" and authenticate(repo, "j@corp.com", PW).ok


def test_existing_account_not_promoted_with_wrong_password(repo):
    s = settings(admin_setup_code="SETUP-123")
    signup(repo, "j@corp.com", "김", PW, s)
    assert signup(repo, "j@corp.com", "공격자", "Other-pass-123", s, setup_code="SETUP-123") == accounts.RECEIVED
    u = repo.get_user("j@corp.com")
    assert u["role"] == "viewer" and u["status"] == "pending" and u["name"] == "김"   # 비밀번호 모르면 아무 변화 없음


def test_existing_account_not_promoted_once_admin_exists(repo):
    s = settings(admin_setup_code="SETUP-123")
    signup(repo, "boss@corp.com", "대표", PW, s, setup_code="SETUP-123")
    signup(repo, "j@corp.com", "김", PW, s)
    assert signup(repo, "j@corp.com", "김", PW, s, setup_code="SETUP-123") == accounts.RECEIVED
    assert repo.get_user("j@corp.com")["role"] == "viewer"


def test_new_signup_with_code_returns_admin_ready(repo):
    assert signup(repo, "a@x.com", "A", PW, settings(admin_setup_code="C"), setup_code="C") == accounts.ADMIN_READY
