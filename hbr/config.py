"""환경설정: 환경변수(.env) → Streamlit secrets 순으로 조회한다."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _get(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value:
        return value
    # 스크립트(수집/메일)에서는 streamlit 을 불러오지 않는다
    if "streamlit" in sys.modules:
        try:
            import streamlit as st

            return str(st.secrets.get(name, default))
        except Exception:
            return default
    return default


_PLACEHOLDER = ("your_", "https://your_", "xxxx", "changeme", "<")


def _is_placeholder(value: str) -> bool:
    """.env.example 을 그대로 복사했을 때의 자리표시 값(YOUR_..., <...>)은 설정되지 않은 것으로 본다."""
    v = (value or "").strip().lower()
    return not v or v.startswith(_PLACEHOLDER) or "your_project" in v or "your_service" in v


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
        supabase_url=_get("SUPABASE_URL"),
        supabase_key=_get("SUPABASE_SECRET_KEY") or _get("SUPABASE_SERVICE_ROLE_KEY"),
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
