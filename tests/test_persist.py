import time

from hbr.auth import persist

S = "test-secret"
ROW = {"id": 7, "password_hash": "pbkdf2_sha256$1$aaa$bbb", "email": "a@b.co"}
DB = {7: ROW}


def lookup(uid):
    return DB.get(uid)


def test_roundtrip_returns_row():
    t = persist.make_token(S, ROW)
    assert persist.verify_token(S, t, lookup) == ROW


def test_expired_token_is_rejected():
    t = persist.make_token(S, ROW, days=1, now=time.time() - 3 * 86400)
    assert persist.verify_token(S, t, lookup) is None


def test_password_change_invalidates_old_token():
    t = persist.make_token(S, ROW)
    DB[7] = {**ROW, "password_hash": "pbkdf2_sha256$1$ccc$ddd"}
    try:
        assert persist.verify_token(S, t, lookup) is None
    finally:
        DB[7] = ROW


def test_tampered_or_foreign_tokens_are_rejected():
    t = persist.make_token(S, ROW)
    uid, exp, sig = t.split(".")
    for bad in (f"8.{exp}.{sig}", f"{uid}.{int(exp) + 999}.{sig}", f"{uid}.{exp}.{'0' * 40}", "garbage", "", None, "1.2", "a.b.c"):
        assert persist.verify_token(S, bad, lookup) is None
    assert persist.verify_token("other-secret", t, lookup) is None        # 다른 서버 비밀값
    assert persist.verify_token("", t, lookup) is None                    # 비밀값이 없으면 기능 꺼짐
    assert persist.verify_token(S, t, lambda uid: None) is None           # 삭제된 사용자


def test_cookie_js_set_and_clear():
    assert "Max-Age=0" in persist.cookie_js(None) and persist.COOKIE in persist.cookie_js(None)
    js = persist.cookie_js("7.123.abc")
    assert "7.123.abc" in js and "Max-Age=1209600" in js and "SameSite=Lax" in js
