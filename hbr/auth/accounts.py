"""이메일 가입 + 관리자 승인 계정 관리 (UI 와 분리된 순수 로직 — Repo 만 의존).

보안 설계
- 가입 요청은 항상 status='pending' (관리자 승인 전에는 아무 데이터도 볼 수 없음)
- 가입/로그인 응답은 계정 존재 여부를 드러내지 않는다 (동일 문구·동일 소요시간)
- 연속 실패 5회 → 15분 잠금, 비밀번호는 PBKDF2 해시로만 저장
- 마지막 활성 관리자는 강등·비활성화·거절할 수 없다 (관리자 잠김 방지)
- 최초 관리자는 ADMIN_SETUP_CODE 로만 만들 수 있고, 활성 관리자가 한 명이라도 있으면 코드는 무효
"""
from __future__ import annotations

import hmac
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ..constants import ROLES
from . import passwords
from .rbac import domain_allowed

MAX_FAILS = 5
LOCK_MINUTES = 15
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
RECEIVED = "가입 신청이 접수되었습니다. 관리자 승인 후 로그인할 수 있습니다."


class AccountError(ValueError):
    """사용자에게 그대로 보여줄 수 있는 메시지를 담는다."""


@dataclass
class AuthResult:
    ok: bool
    user: dict | None = None
    reason: str = ""        # bad | locked | pending | disabled | ""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value) -> datetime | None:
    """ISO 문자열(+00:00/Z/시간대 없음)을 UTC 기준 aware datetime 으로."""
    if not value:
        return None
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def status_of(row: dict) -> str:
    return row.get("status") or "approved"           # 컬럼 도입 전 사용자는 승인 상태


def active_admin_count(repo) -> int:
    return sum(1 for u in repo.rows("users") if u.get("role") == "admin" and status_of(u) == "approved"
               and u.get("is_active", True))


def _is_last_admin(repo, user_id: int) -> bool:
    rows = [u for u in repo.rows("users") if u["id"] == user_id]
    if not rows:
        return False
    u = rows[0]
    is_admin = u.get("role") == "admin" and status_of(u) == "approved" and u.get("is_active", True)
    return is_admin and active_admin_count(repo) <= 1


# ── 가입 ────────────────────────────────────────────────────────
def signup(repo, email: str, name: str, password: str, settings, setup_code: str | None = None) -> str:
    """가입 신청. 성공/중복 모두 같은 안내 문구를 돌려준다(계정 존재 여부 비노출). 입력 오류만 AccountError."""
    email, name = normalize_email(email), (name or "").strip()
    if not _EMAIL.match(email):
        raise AccountError("이메일 형식이 올바르지 않습니다.")
    if not name or len(name) > 50:
        raise AccountError("이름을 50자 이내로 입력해 주세요.")
    if not domain_allowed(email, settings.allowed_email_domains):
        raise AccountError("허용되지 않은 이메일 도메인입니다. 관리자에게 문의하세요.")
    problem = passwords.password_problem(password, email)
    if problem:
        raise AccountError(problem)

    pw_hash = passwords.hash_password(password)       # 존재 여부와 무관하게 항상 해시 (응답 시간 균일화)
    if repo.get_user(email):
        return RECEIVED

    role, status, approved_at = "viewer", "pending", None
    code = settings.admin_setup_code
    if code and setup_code and hmac.compare_digest(code.encode(), setup_code.strip().encode()) \
            and active_admin_count(repo) == 0:
        role, status, approved_at = "admin", "approved", _now().isoformat()
    repo.insert("users", [{"email": email, "name": name, "role": role, "status": status, "is_active": True,
                           "report_enabled": True, "password_hash": pw_hash, "failed_attempts": 0,
                           "must_change_password": False, "approved_at": approved_at}])
    return RECEIVED


# ── 로그인 ──────────────────────────────────────────────────────
def authenticate(repo, email: str, password: str) -> AuthResult:
    """비밀번호를 먼저 검증하고 그 다음에 상태를 안내한다 (비밀번호를 모르면 상태도 알 수 없음)."""
    email = normalize_email(email)
    row = repo.get_user(email) if email else None
    if row is None:
        passwords.dummy_verify(password)
        return AuthResult(False, reason="bad")

    locked = _parse_ts(row.get("locked_until"))
    if locked and locked > _now():
        return AuthResult(False, reason="locked")

    if not passwords.verify_password(password, row.get("password_hash")):
        fails = int(row.get("failed_attempts") or 0) + 1
        vals: dict = {"failed_attempts": fails}
        if fails >= MAX_FAILS:
            vals = {"failed_attempts": 0, "locked_until": (_now() + timedelta(minutes=LOCK_MINUTES)).isoformat()}
        repo.update("users", vals, [("id", "eq", row["id"])])
        return AuthResult(False, reason="bad")

    repo.update("users", {"failed_attempts": 0, "locked_until": None}, [("id", "eq", row["id"])])
    st = status_of(row)
    if st == "pending":
        return AuthResult(False, reason="pending")
    if st != "approved" or not row.get("is_active", True):
        return AuthResult(False, reason="disabled")
    repo.update("users", {"last_login_at": _now().isoformat()}, [("id", "eq", row["id"])])
    return AuthResult(True, user={**row, "failed_attempts": 0})


# ── 관리자 작업 ─────────────────────────────────────────────────
def approve(repo, user_id: int, role: str, admin_id: int | None) -> None:
    if role not in ROLES:
        raise AccountError("알 수 없는 역할입니다.")
    repo.update("users", {"status": "approved", "role": role, "is_active": True, "approved_by": admin_id,
                          "approved_at": _now().isoformat()}, [("id", "eq", user_id)])


def reject(repo, user_id: int) -> None:
    if _is_last_admin(repo, user_id):
        raise AccountError("마지막 관리자는 거절할 수 없습니다.")
    repo.update("users", {"status": "rejected"}, [("id", "eq", user_id)])


def update_user(repo, user_id: int, *, role: str | None = None, is_active: bool | None = None,
                report_enabled: bool | None = None, name: str | None = None) -> None:
    vals: dict = {}
    if role is not None:
        if role not in ROLES:
            raise AccountError("알 수 없는 역할입니다.")
        if role != "admin" and _is_last_admin(repo, user_id):
            raise AccountError("마지막 관리자는 강등할 수 없습니다. 먼저 다른 관리자를 지정하세요.")
        vals["role"] = role
    if is_active is not None:
        if not is_active and _is_last_admin(repo, user_id):
            raise AccountError("마지막 관리자는 비활성화할 수 없습니다.")
        vals["is_active"] = is_active
    if report_enabled is not None:
        vals["report_enabled"] = report_enabled
    if name is not None:
        vals["name"] = name.strip()[:50]
    if vals:
        repo.update("users", vals, [("id", "eq", user_id)])


def reset_password(repo, user_id: int) -> str:
    """임시 비밀번호를 발급(화면에 한 번만 표시). 다음 로그인 때 변경을 강제한다."""
    temp = passwords.generate_temp_password()
    repo.update("users", {"password_hash": passwords.hash_password(temp), "must_change_password": True,
                          "failed_attempts": 0, "locked_until": None}, [("id", "eq", user_id)])
    return temp


def change_password(repo, user_id: int, old: str | None, new: str, require_old: bool = True) -> None:
    rows = [u for u in repo.rows("users") if u["id"] == user_id]
    if not rows:
        raise AccountError("계정을 찾을 수 없습니다.")
    row = rows[0]
    if require_old and not passwords.verify_password(old or "", row.get("password_hash")):
        raise AccountError("현재 비밀번호가 올바르지 않습니다.")
    problem = passwords.password_problem(new, row["email"])
    if problem:
        raise AccountError(problem)
    if passwords.verify_password(new, row.get("password_hash")):
        raise AccountError("현재와 다른 비밀번호를 입력해 주세요.")
    repo.update("users", {"password_hash": passwords.hash_password(new), "must_change_password": False},
                [("id", "eq", user_id)])
