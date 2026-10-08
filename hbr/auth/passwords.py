"""비밀번호 해시/검증/정책. 표준 라이브러리만 사용 (PBKDF2-HMAC-SHA256, 솔트, 상수시간 비교)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

ITERATIONS = 600_000        # OWASP 권장(PBKDF2-SHA256). 테스트에서는 낮춰서 사용
MIN_LENGTH, MAX_LENGTH = 10, 128
_COMMON = {"1234567890", "0123456789", "qwertyuiop", "password12", "password123", "password1234",
           "1q2w3e4r5t", "abcdefghij", "iloveyou12", "admin12345", "asdfghjkl1"}


def hash_password(password: str, iterations: int | None = None) -> str:
    iters = iterations or ITERATIONS
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters)
    b64 = lambda b: base64.b64encode(b).decode()
    return f"pbkdf2_sha256${iters}${b64(salt)}${b64(dk)}"


def verify_password(password: str, stored: str | None) -> bool:
    """저장 해시가 없거나 형식이 틀리면 False (예외를 던지지 않는다)."""
    try:
        algo, iters, salt, expected = (stored or "").split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), base64.b64decode(salt), int(iters))
        return hmac.compare_digest(dk, base64.b64decode(expected))
    except (ValueError, TypeError):
        return False


def dummy_verify(password: str) -> None:
    """존재하지 않는 계정에도 같은 시간을 쓰도록 해 계정 존재 여부가 응답 시간으로 드러나지 않게 한다."""
    verify_password(password, hash_password("dummy-password-value", ITERATIONS))


def password_problem(password: str, email: str = "") -> str | None:
    """정책 위반 사유(한국어) 또는 None."""
    if len(password) < MIN_LENGTH:
        return f"비밀번호는 {MIN_LENGTH}자 이상이어야 합니다."
    if len(password) > MAX_LENGTH:
        return f"비밀번호는 {MAX_LENGTH}자 이하여야 합니다."
    classes = sum(any(f(c) for c in password) for f in (str.isalpha, str.isdigit, lambda c: not c.isalnum()))
    if classes < 2:
        return "비밀번호는 영문, 숫자, 특수문자 중 2가지 이상을 섞어 주세요."
    low = password.lower()
    if low in _COMMON or len(set(password)) < 4:
        return "너무 흔하거나 단순한 비밀번호입니다."
    if email and (low == email.lower() or email.lower().split("@")[0] in low and len(email.split("@")[0]) >= 4):
        return "비밀번호에 이메일 아이디를 포함할 수 없습니다."
    return None


def generate_temp_password() -> str:
    """관리자 초기화용 임시 비밀번호 (정책 충족: 영문+숫자 혼합, 12자)."""
    while True:
        pw = secrets.token_urlsafe(9)
        if password_problem(pw) is None and any(c.isdigit() for c in pw) and any(c.isalpha() for c in pw):
            return pw
