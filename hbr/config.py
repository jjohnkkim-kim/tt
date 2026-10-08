"""환경설정: 환경변수(.env) → Streamlit secrets 순으로 조회한다."""
from __future__ import annotations

import os
import re
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
    admin_setup_code: str       # 최초 관리자 생성용 일회성 코드 (활성 관리자가 없을 때만 유효)
    admin_emails: list[str]
    allowed_email_domains: list[str]
    auto_provision: bool
    app_base_url: str
    own_company: str

    @property
    def use_supabase(self) -> bool:
        if self.data_backend == "memory":
            return False
        if self.data_backend == "supabase":
            return True
        return bool(self.supabase_url and self.supabase_key)


def clean_supabase_url(raw: str) -> str:
    """Secrets 붙여넣기 실수(공백·줄바꿈·따옴표·https:// 누락·/rest/v1 접미사)를 정리."""
    u = (raw or "").strip().strip("\"'").strip()
    if not u:
        return ""
    if not re.match(r"^https?://", u, re.I):
        u = "https://" + u
    u = re.sub(r"/(rest|auth|storage|realtime)/v1.*$", "", u)
    return u.rstrip("/")


def clean_secret(raw: str) -> str:
    return (raw or "").strip().strip("\"'").strip()


def bids_only() -> bool:
    """BIDS_ONLY=true 이면 입찰공고만 수집·표시 (낙찰/계약은 데이터량이 커서 제외)."""
    return _get("BIDS_ONLY", "false").strip().lower() in ("1", "true", "yes", "y")


def telegram_config() -> tuple[str, str]:
    """(봇 토큰, chat id). 텔레그램 푸시용."""
    return _get("TELEGRAM_BOT_TOKEN").strip(), _get("TELEGRAM_CHAT_ID").strip()


def get_settings() -> Settings:
    return Settings(
        service_key=clean_secret(_get("SERVICE_KEY")),
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
        admin_setup_code=_get("ADMIN_SETUP_CODE").strip(),
        admin_emails=_list("ADMIN_EMAILS"),
        allowed_email_domains=_list("ALLOWED_EMAIL_DOMAINS"),
        auto_provision=_bool("AUTO_PROVISION", True),
        app_base_url=_get("APP_BASE_URL", "http://localhost:8501").rstrip("/"),
        own_company=_get("OWN_COMPANY", "SK플라즈마"),
    )
