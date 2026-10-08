"""로그인 유지: 서명된 '입장권'(쿠키)을 브라우저에 보관했다가 새로고침 후에도 자동 로그인.

토큰 = uid.만료시각.서명   서명 = HMAC(비밀값, uid|만료|비밀번호지문)
- 비밀번호가 바뀌면 지문이 달라져 옛 토큰은 즉시 무효 (다른 기기 로그인도 함께 로그아웃)
- 계정이 비활성/미승인이면 토큰이 있어도 통과하지 못한다 (호출하는 쪽에서 DB 상태를 다시 확인)
- 비밀값이 없으면 기능을 끈다 (로그인은 예전처럼 새로고침 전까지만 유지)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time

COOKIE = "hbr_session"
DEFAULT_DAYS = 14


def _key(secret: str) -> bytes:
    return hashlib.sha256(f"hbr-session-v1|{secret}".encode()).digest()


def _fingerprint(row: dict) -> str:
    """비밀번호 해시의 일부. 비밀번호를 바꾸면 달라진다 (해시 자체는 토큰에 담지 않는다)."""
    return hashlib.sha256(str(row.get("password_hash") or "").encode()).hexdigest()[:16]


def _sig(secret: str, uid: int, exp: int, fp: str) -> str:
    return hmac.new(_key(secret), f"{uid}|{exp}|{fp}".encode(), hashlib.sha256).hexdigest()[:40]


def make_token(secret: str, row: dict, days: int = DEFAULT_DAYS, now: float | None = None) -> str:
    exp = int((now if now is not None else time.time()) + days * 86400)
    return f"{row['id']}.{exp}.{_sig(secret, row['id'], exp, _fingerprint(row))}"


def verify_token(secret: str, token: str | None, row_lookup, now: float | None = None) -> dict | None:
    """유효하면 사용자 행(dict), 아니면 None. row_lookup(uid) -> dict | None"""
    if not secret or not token:
        return None
    try:
        uid_s, exp_s, sig = token.split(".")
        uid, exp = int(uid_s), int(exp_s)
    except (ValueError, AttributeError):
        return None
    if exp < (now if now is not None else time.time()):
        return None
    row = row_lookup(uid)
    if not row:
        return None
    if not hmac.compare_digest(_sig(secret, uid, exp, _fingerprint(row)), sig):
        return None
    return row


def cookie_js(token: str | None, days: int = DEFAULT_DAYS) -> str:
    """브라우저에 쿠키를 심거나(token) 지우는(None) 아주 작은 스크립트."""
    value = json.dumps(token or "")
    age = days * 86400 if token else 0
    return ("<script>(function(){var s=(location.protocol==='https:')?'; Secure':'';"
            f"document.cookie='{COOKIE}='+encodeURIComponent({value})+'; Max-Age={age}; Path=/; SameSite=Lax'+s;"
            "try{window.parent.document.cookie='%s='+encodeURIComponent(%s)+'; Max-Age=%d; Path=/; SameSite=Lax'+s;}catch(e){}"
            "})();</script>" % (COOKIE, value, age))
