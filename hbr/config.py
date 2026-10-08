"""환경설정: 환경변수(.env) → Streamlit secrets 순으로 조회한다."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _get(name: str, default: str = "") -> str:
    # 앱(Streamlit) 실행 중에는 Secrets 를 먼저 본다: Cloud 에서 Secrets 를 고치면 환경변수는 재시작 전까지
    # 옛 값이 남을 수 있기 때문. 스크립트(수집/메일)는 streamlit 을 불러오지 않으므로 환경변수(.env)만 쓴다.
    if "streamlit" in sys.modules:
        try:
            import streamlit as st

            if name in st.secrets:
                value = st.secrets[name]
                if value not in (None, ""):
                    return str(value)
        except Exception:       # noqa: BLE001 — secrets.toml 이 없으면 예외
            pass
    value = os.getenv(name)
    return value if value else default


_PLACEHOLDER = ("your_", "https://your_", "xxxx", "changeme", "<")


def _is_placeholder(value: str) -> bool:
    """.env.example 을 그대로 복사했을 때의 자리표시 값(YOUR_..., <...>)은 설정되지 않은 것으로 본다."""
    v = (value or "").strip().lower()
    return not v or v.startswith(_PLACEHOLDER) or "your_project" in v or "your_service" in v


_INVISIBLE = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff\u00a0"), None)


def clean_secret(value: str) -> str:
    """복사·붙여넣기로 섞이는 앞뒤 공백, 따옴표, 보이지 않는 문자(제로폭 공백·BOM·nbsp)를 제거."""
    return (value or "").translate(_INVISIBLE).strip().strip("'\"").strip()


def clean_supabase_url(value: str) -> str:
    """Project URL 을 'https://<id>.supabase.co' 형태로 정규화.
    흔한 실수: 공백/보이지 않는 문자, https:// 누락·중복, /rest/v1/ 같은 경로, 끝의 슬래시."""
    from urllib.parse import urlparse

    v = clean_secret(value)
    if not v:
        return ""
    while v.lower().startswith(("https://https://", "https://http://", "http://https://")):
        v = v.split("://", 1)[1]
    if "://" not in v:
        v = "https://" + v
    u = urlparse(v)
    host = (u.hostname or "").strip(".")
    return f"{u.scheme}://{host}" + (f":{u.port}" if u.port else "") if host else v


def key_kind(key: str) -> str:
    """키 종류만 판별(값은 노출하지 않음)."""
    k = clean_secret(key)
    if not k:
        return "없음"
    if k.startswith("sb_secret_"):
        return f"Secret key (sb_secret_…, {len(k)}자)"
    if k.startswith("sb_publishable_"):
        return f"Publishable key (sb_publishable_…, {len(k)}자) — 잘못된 키 종류"
    if k.startswith("eyJ"):
        return f"JWT 형식(레거시 anon 또는 service_role, {len(k)}자)"
    return f"알 수 없는 형식({len(k)}자)"


def _optional(name: str) -> str:
    """선택 설정. Azure secret 은 빈 값이 불가해 'none' 을 비활성으로 취급."""
    v = _get(name)
    return "" if v.lower() == "none" else v


def _bool(name: str, default: bool) -> bool:
    raw = _get(name, "")
    if raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _list(name: str) -> list[str]:
    return [x.strip().lower() for x in _get(name).split(",") if x.strip()]


@dataclass(frozen=True)
class Settings:
    service_key: str
    g2b_base_url: str
    supabase_url: str
    supabase_key: str
    data_backend: str
    anthropic_api_key: str
    openai_api_key: str
    claude_model: str
    openai_model: str
    llm_provider: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    mail_from: str
    mail_dry_run: bool
    report_subject: str
    auth_disabled: bool
    auth_mode: str              # password(이메일 가입+관리자 승인, 기본) | entra(Microsoft)
    admin_setup_code: str       # 최초 관리자 생성용 일회성 코드 (관리자가 없을 때만 유효)
    admin_emails: list[str]
    allowed_email_domains: list[str]
    auto_provision: bool
    app_base_url: str
    own_company: str
    teams_webhook_url: str
    slack_webhook_url: str
    solapi_api_key: str
    solapi_api_secret: str
    kakao_pf_id: str            # 카카오 비즈니스 채널(발신프로필) ID
    kakao_sender: str           # 대행사에 등록된 발신번호
    kakao_tpl_alert: str        # 승인된 알림톡 템플릿 ID (즉시 알림)
    kakao_tpl_report: str       # 승인된 알림톡 템플릿 ID (Daily Report)

    @property
    def storage_label(self) -> str:
        """화면 표시용 저장소 상태 (비밀 값 없음: 호스트명만)."""
        if not self.use_supabase:
            return "demo"
        from urllib.parse import urlparse

        return urlparse(self.supabase_url).hostname or "supabase"

    def storage_key(self) -> tuple:
        """저장소 연결을 다시 만들어야 하는지 판단하는 키 (키 원문 대신 해시)."""
        import hashlib

        return (self.use_supabase, self.supabase_url, hashlib.sha256(self.supabase_key.encode()).hexdigest()[:16])

    @property
    def kakao_enabled(self) -> bool:
        return all([self.solapi_api_key, self.solapi_api_secret, self.kakao_pf_id, self.kakao_sender])

    @property
    def use_supabase(self) -> bool:
        if self.data_backend == "memory":
            return False
        if self.data_backend == "supabase":
            return True
        return not (_is_placeholder(self.supabase_url) or _is_placeholder(self.supabase_key))


def get_settings() -> Settings:
    return Settings(
        service_key=_get("SERVICE_KEY"),
        g2b_base_url=_get("G2B_BASE_URL", "https://apis.data.go.kr/1230000/ao/PubDataOpnStdService").rstrip("/"),
        supabase_url=clean_supabase_url(_get("SUPABASE_URL")),
        supabase_key=clean_secret(_get("SUPABASE_SECRET_KEY") or _get("SUPABASE_SERVICE_ROLE_KEY")),
        data_backend=_get("DATA_BACKEND", "auto").lower(),
        anthropic_api_key=_get("ANTHROPIC_API_KEY"),
        openai_api_key=_get("OPENAI_API_KEY"),
        claude_model=_get("CLAUDE_MODEL", "claude-sonnet-5-5"),
        openai_model=_get("OPENAI_MODEL", "gpt-4.1"),
        llm_provider=_get("LLM_PROVIDER", "auto").lower(),
        smtp_host=_get("SMTP_HOST", "smtp.office365.com"),
        smtp_port=int(_get("SMTP_PORT", "587") or 587),
        smtp_user=_get("SMTP_USER"),
        smtp_password=_get("SMTP_PASSWORD"),
        mail_from=_get("MAIL_FROM", "Hospital Bid Radar <bidradar@localhost>"),
        mail_dry_run=_bool("MAIL_DRY_RUN", True),
        report_subject=_get("REPORT_SUBJECT", "[Hospital Bid Radar] Daily Report ({date})"),
        auth_disabled=_bool("AUTH_DISABLED", False),
        auth_mode="entra" if _get("AUTH_MODE", "password").lower() == "entra" else "password",
        admin_setup_code=_optional("ADMIN_SETUP_CODE"),
        admin_emails=_list("ADMIN_EMAILS"),
        allowed_email_domains=_list("ALLOWED_EMAIL_DOMAINS"),
        auto_provision=_bool("AUTO_PROVISION", True),
        app_base_url=_get("APP_BASE_URL", "http://localhost:8501").rstrip("/"),
        own_company=_get("OWN_COMPANY", "SK플라즈마"),
        teams_webhook_url=_optional("TEAMS_WEBHOOK_URL"),
        slack_webhook_url=_optional("SLACK_WEBHOOK_URL"),
        solapi_api_key=_optional("SOLAPI_API_KEY"),
        solapi_api_secret=_optional("SOLAPI_API_SECRET"),
        kakao_pf_id=_optional("KAKAO_PF_ID"),
        kakao_sender=_optional("KAKAO_SENDER"),
        kakao_tpl_alert=_optional("KAKAO_TPL_ALERT"),
        kakao_tpl_report=_optional("KAKAO_TPL_REPORT"),
    )
