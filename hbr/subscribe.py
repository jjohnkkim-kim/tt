"""메일 구독: 이메일 입력 → 인증코드 확인 → Daily Report 수신자로 등록 / 취소.

인증코드는 서버에 저장하지 않고 HMAC 으로 만든다(주소+시간대 기준). 같은 주소·같은 시간대는 같은 코드이고,
유효시간은 최대 2 * WINDOW_MIN 분이다. 서명 비밀값이 없으면 기능을 사용할 수 없다.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import time
from html import escape

from .config import Settings, _get
from .reports.mailer import send_email
from .store.repo import Repo

WINDOW_MIN = 15
CODE_DIGITS = 6
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)+$")


class SubscribeError(ValueError):
    pass


def secret_for(settings: Settings) -> str:
    return _get("SUBSCRIBE_SECRET") or settings.supabase_key


def normalize_email(raw: str) -> str:
    email = (raw or "").strip().lower()
    if len(email) > 254 or not _EMAIL_RE.match(email):
        raise SubscribeError("이메일 형식이 올바르지 않습니다.")
    return email


def check_domain(email: str) -> None:
    allowed = [d.strip().lower().lstrip("@") for d in _get("SUBSCRIBE_ALLOWED_DOMAINS").split(",") if d.strip()]
    if allowed and email.rsplit("@", 1)[1] not in allowed:
        raise SubscribeError(f"허용된 도메인({', '.join(allowed)})의 메일만 구독할 수 있습니다.")


def _code(secret: str, email: str, purpose: str, bucket: int) -> str:
    mac = hmac.new(secret.encode(), f"{purpose}|{email}|{bucket}".encode(), hashlib.sha256).digest()
    return f"{int.from_bytes(mac[:8], 'big') % 10 ** CODE_DIGITS:0{CODE_DIGITS}d}"


def _bucket(now: float | None) -> int:
    return int((now if now is not None else time.time()) // (WINDOW_MIN * 60))


def issue_code(secret: str, email: str, purpose: str, now: float | None = None) -> str:
    if not secret:
        raise SubscribeError("구독 기능이 설정되지 않았습니다 (SUBSCRIBE_SECRET 또는 SUPABASE_SECRET_KEY).")
    return _code(secret, email, purpose, _bucket(now))


def verify_code(secret: str, email: str, purpose: str, code: str, now: float | None = None) -> bool:
    if not secret or not re.fullmatch(rf"\d{{{CODE_DIGITS}}}", (code or "").strip()):
        return False
    b = _bucket(now)
    return any(hmac.compare_digest(_code(secret, email, purpose, x), code.strip()) for x in (b, b - 1))


PURPOSES = {"subscribe": "구독 신청", "unsubscribe": "구독 취소"}


def send_code(settings: Settings, email: str, purpose: str) -> str:
    """인증코드 메일 발송. 반환: send_email 결과('sent'/'dry_run')."""
    code = issue_code(secret_for(settings), email, purpose)
    label = PURPOSES[purpose]
    html = (f"<div style='font-family:Malgun Gothic,Arial'><p>Hospital Bid Radar {escape(label)} 인증코드입니다.</p>"
            f"<p style='font-size:28px;letter-spacing:6px'><b>{code}</b></p>"
            f"<p style='color:#55637a'>{WINDOW_MIN}~{2 * WINDOW_MIN}분 안에 입력해 주세요. "
            f"본인이 요청하지 않았다면 이 메일을 무시하세요.</p></div>")
    return send_email(settings, email, f"[Hospital Bid Radar] {label} 인증코드 {code}", html,
                      f"{label} 인증코드: {code} ({WINDOW_MIN}~{2 * WINDOW_MIN}분 유효)")


def subscribe(repo: Repo, email: str) -> str:
    """인증이 끝난 주소를 수신자로 등록. 반환: 'created' | 'enabled' | 'already'."""
    u = repo.get_user(email)
    if u is None:
        repo.ensure_user(email, email.split("@")[0], "viewer")
        return "created"
    if not u.get("is_active"):
        raise SubscribeError("비활성화된 계정입니다. 관리자에게 문의하세요.")
    if u.get("report_enabled"):
        return "already"
    repo.update("users", {"report_enabled": True}, [("id", "eq", u["id"])])
    return "enabled"


def unsubscribe(repo: Repo, email: str) -> bool:
    u = repo.get_user(email)
    if not u or not u.get("report_enabled"):
        return False
    repo.update("users", {"report_enabled": False}, [("id", "eq", u["id"])])
    return True
