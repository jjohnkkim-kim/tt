"""Microsoft Teams 채널 알림 (Workflows/Power Automate 웹훅 + Adaptive Card).

설정: Teams 채널 > 워크플로 > "웹후크 요청을 받으면 채널에 게시" 템플릿으로 URL 발급 → TEAMS_WEBHOOK_URL.
(구 Office 365 커넥터 웹훅은 종료 예정이라 Workflows 웹훅을 기준으로 한다.)
웹훅 URL 자체가 비밀이므로 .env / Secrets 로만 관리한다.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date
from urllib.parse import urlparse

import requests

from ..constants import ALERT_TYPES
from ..utils import fmt_won

log = logging.getLogger(__name__)

# 임의 URL 로 데이터가 나가는 것(오설정·SSRF)을 막기 위해 Microsoft 도메인만 허용
ALLOWED_HOST_SUFFIXES = (".logic.azure.com", ".powerplatform.com", ".webhook.office.com", ".office.com")
MAX_ITEMS = 10
ICON = {"NEW_BID": "📋", "CONTRACT_EXPIRY": "⏰", "COMPETITOR_AWARD": "🎯"}


class TeamsError(RuntimeError):
    pass


def validate_webhook(url: str) -> str:
    u = urlparse(url or "")
    host = (u.hostname or "").lower()
    if u.scheme != "https" or not any(host.endswith(sfx) for sfx in ALLOWED_HOST_SUFFIXES):
        raise TeamsError("TEAMS_WEBHOOK_URL 은 https 이고 Microsoft(Workflows/Teams) 도메인이어야 합니다")
    return url


_MD_LINK = re.compile(r"[\[\]]")


def _t(text, limit: int = 300) -> str:
    """외부(공고명 등) 텍스트 정리: Markdown 링크 문법 제거(채널에서 피싱 링크 방지) + 길이 제한."""
    s = _MD_LINK.sub("", str(text or "")).replace("\r", " ").replace("\n", " ").strip()
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _card(body: list[dict], url: str | None = None) -> dict:
    content = {"$schema": "http://adaptivecards.io/schemas/adaptive-card.json", "type": "AdaptiveCard",
               "version": "1.4", "msteams": {"width": "Full"}, "body": body}
    if url and url.startswith("https://"):
        content["actions"] = [{"type": "Action.OpenUrl", "title": "대시보드 열기", "url": url}]
    return {"type": "message", "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive",
                                                "contentUrl": None, "content": content}]}


def alerts_card(alerts: list[dict], base_url: str = "") -> dict:
    body: list[dict] = [{"type": "TextBlock", "text": f"🔔 Hospital Bid Radar 알림 {len(alerts)}건",
                         "weight": "Bolder", "size": "Medium", "wrap": True}]
    for a in alerts[:MAX_ITEMS]:
        body.append({"type": "Container", "separator": True, "items": [
            {"type": "TextBlock", "wrap": True, "weight": "Bolder",
             "text": f"{ICON.get(a['alert_type'], '•')} {ALERT_TYPES.get(a['alert_type'], a['alert_type'])} · " + _t(a["title"], 150),
             "color": "Attention" if a.get("severity") == "high" else "Default"},
            {"type": "TextBlock", "wrap": True, "isSubtle": True, "spacing": "None", "text": _t(a.get("message"))}]})
    if len(alerts) > MAX_ITEMS:
        body.append({"type": "TextBlock", "text": f"외 {len(alerts) - MAX_ITEMS}건은 대시보드에서 확인하세요.", "isSubtle": True})
    return _card(body, base_url or None)


def report_card(data: dict, base_url: str = "") -> dict:
    s = data["summary"]
    facts = [("신규 입찰", f"{s['new_bids']}건"), ("마감 임박", f"{s['closing']}건"),
             ("계약만료 예정(90일)", f"{s['expiring']}건"), ("경쟁사 신규 수주", f"{s['competitor_awards']}건")]
    body: list[dict] = [
        {"type": "TextBlock", "text": f"📡 Daily Report · {data['date']}", "weight": "Bolder", "size": "Medium"},
        {"type": "FactSet", "facts": [{"title": k, "value": v} for k, v in facts]},
        {"type": "TextBlock", "text": "Opportunity TOP 3", "weight": "Bolder", "separator": True}]
    for t in data["top"][:3]:
        body.append({"type": "TextBlock", "wrap": True, "spacing": "Small",
                     "text": f"{t['rank']}. {_t(t['hospital'], 60)} — {t['score']}점 · {_t(t['reasons'], 160)}"})
    if data.get("actions"):
        a = data["actions"][0]
        body += [{"type": "TextBlock", "text": "🤖 AI 추천 Action", "weight": "Bolder", "separator": True},
                 {"type": "TextBlock", "wrap": True,
                  "text": f"{_t(a['hospital'], 60)}: " + ", ".join(_t(x, 80) for x in a["actions"][:3])}]
    return _card(body, base_url or None)


def send_card(webhook_url: str, card: dict, retries: int = 3, session=None) -> None:
    validate_webhook(webhook_url)
    http = session or requests
    last = None
    for attempt in range(retries):
        try:
            r = http.post(webhook_url, json=card, timeout=15)
            if r.status_code in (200, 202):
                return
            last = f"HTTP {r.status_code}"
            if r.status_code < 500 and r.status_code != 429:     # 4xx(잘못된 URL/카드) 는 재시도 무의미
                break
        except requests.RequestException as e:
            last = type(e).__name__
        time.sleep(2 ** attempt)
    raise TeamsError(f"Teams 전송 실패: {last}")     # URL(비밀) 은 메시지에 넣지 않는다
