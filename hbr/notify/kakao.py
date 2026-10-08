"""카카오톡 알림톡 (비즈니스 메시지) — 대행사 API 어댑터.

카카오톡에는 Teams/Slack 같은 채널 웹훅이 없다. 회사 알림은 '알림톡'(카카오 비즈채널 + 사전 승인 템플릿 +
수신자 휴대폰번호)을 대행사 API 로 보낸다. 대행사를 바꿀 수 있도록 `AlimtalkProvider` 로 분리했고 현재 Solapi 만 구현.

법/운영 유의: 휴대폰번호는 개인정보 → 본인이 직접 입력 + 수신 동의(kakao_opt_in)한 사용자에게만 발송한다.
알림톡은 정보성 메시지만 가능(광고성 문구 금지)하고 템플릿은 카카오 승인 후에만 쓸 수 있다.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import re
import secrets
import time
from typing import Protocol

import requests

from .common import clean_text

SOLAPI_URL = "https://api.solapi.com/messages/v4/send"

# 승인받을 템플릿 본문 (변수는 #{...}). docs/ARCHITECTURE.md 에도 동일하게 기재
TEMPLATE_ALERT = """[Hospital Bid Radar] 새 알림 #{건수}건
#{제목}
#{내용}
자세한 내용은 대시보드에서 확인하세요."""
TEMPLATE_REPORT = """[Hospital Bid Radar] #{날짜} Daily Report
신규 입찰 #{신규입찰}건 / 마감 임박 #{마감임박}건
계약만료 예정 #{계약만료}건 / 경쟁사 신규 수주 #{경쟁사수주}건
상세 리포트는 이메일과 대시보드에서 확인하세요."""

_MOBILE = re.compile(r"^01[016789]\d{7,8}$")


class KakaoError(RuntimeError):
    pass


def normalize_phone(raw: str | None) -> str | None:
    """한국 휴대폰번호를 숫자만(010xxxxxxxx)으로. +82 10-… 형식도 허용. 유효하지 않으면 None."""
    d = re.sub(r"\D", "", raw or "")
    if d.startswith("82"):
        d = "0" + d[2:]
    return d if _MOBILE.match(d) else None


def mask_phone(phone: str) -> str:
    return phone[:3] + "****" + phone[-4:] if len(phone) >= 8 else "****"


class AlimtalkProvider(Protocol):
    def send(self, to: str, template_id: str, variables: dict[str, str]) -> None: ...


class SolapiProvider:
    """Solapi REST API (HMAC-SHA256 인증). 응답/필드는 실계정으로 검증이 필요하다."""

    def __init__(self, api_key: str, api_secret: str, pf_id: str, sender: str, session=None, retries: int = 3):
        self.api_key, self.api_secret, self.pf_id, self.sender = api_key, api_secret, pf_id, sender
        self.http, self.retries = session or requests, retries

    def _auth(self) -> str:
        date = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        salt = secrets.token_hex(16)
        sig = hmac.new(self.api_secret.encode(), (date + salt).encode(), hashlib.sha256).hexdigest()
        return f"HMAC-SHA256 apiKey={self.api_key}, date={date}, salt={salt}, signature={sig}"

    def send(self, to: str, template_id: str, variables: dict[str, str]) -> None:
        phone = normalize_phone(to)
        if not phone:
            raise KakaoError("유효하지 않은 휴대폰번호")
        body = {"message": {"to": phone, "from": re.sub(r"\D", "", self.sender),       # 발신번호는 유선(02/1588 등)도 가능 → 숫자만
                            "kakaoOptions": {"pfId": self.pf_id, "templateId": template_id, "variables": variables}}}
        last = None
        for attempt in range(self.retries):
            try:
                r = self.http.post(SOLAPI_URL, json=body, headers={"Authorization": self._auth()}, timeout=15)
                if r.status_code == 200:
                    return
                last = f"HTTP {r.status_code}"
                if r.status_code < 500 and r.status_code != 429:
                    break
            except requests.RequestException as e:
                last = type(e).__name__
            time.sleep(2 ** attempt)
        # 인증키·전화번호(개인정보)는 오류 메시지에 넣지 않는다
        raise KakaoError(f"알림톡 전송 실패 ({mask_phone(phone)}): {last}")


def get_provider(settings) -> AlimtalkProvider | None:
    if not settings.kakao_enabled:
        return None
    return SolapiProvider(settings.solapi_api_key, settings.solapi_api_secret, settings.kakao_pf_id, settings.kakao_sender)


def _v(text, limit: int) -> str:
    return clean_text(text, limit)


def alert_variables(alerts: list[dict]) -> dict[str, str]:
    """알림톡 변수는 길이 제한이 있어 요약만 담는다 (건수 + 첫 알림)."""
    first = alerts[0]
    return {"#{건수}": str(len(alerts)), "#{제목}": _v(first["title"], 40), "#{내용}": _v(first.get("message"), 100)}


def report_variables(data: dict) -> dict[str, str]:
    s = data["summary"]
    return {"#{날짜}": str(data["date"]), "#{신규입찰}": str(s["new_bids"]), "#{마감임박}": str(s["closing"]),
            "#{계약만료}": str(s["expiring"]), "#{경쟁사수주}": str(s["competitor_awards"])}
