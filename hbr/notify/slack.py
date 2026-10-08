"""Slack 채널 알림 (Incoming Webhook + Block Kit).

설정: Slack 앱 > Incoming Webhooks 활성화 > 채널 추가 → https://hooks.slack.com/services/... → SLACK_WEBHOOK_URL.
웹훅 URL 자체가 비밀이므로 .env / Secrets 로만 관리한다.
"""
from __future__ import annotations

from ..constants import ALERT_TYPES
from .common import clean_text, host_ok, post_with_retry

MAX_ITEMS = 10
ICON = {"NEW_BID": "📋", "CONTRACT_EXPIRY": "⏰", "COMPETITOR_AWARD": "🎯"}


class SlackError(RuntimeError):
    pass


def validate_webhook(url: str) -> str:
    if not host_ok(url, exact=("hooks.slack.com",)):
        raise SlackError("SLACK_WEBHOOK_URL 은 https://hooks.slack.com/ 주소여야 합니다")
    return url


def esc(text, limit: int = 300) -> str:
    """mrkdwn 인젝션 방지: &,<,> 를 이스케이프해 <!channel> 멘션·<url|text> 링크가 만들어지지 않게 한다."""
    s = clean_text(text, limit)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _link_block(base_url: str) -> list[dict]:
    if not (base_url or "").startswith("https://"):
        return []
    return [{"type": "actions", "elements": [{"type": "button", "text": {"type": "plain_text", "text": "대시보드 열기"},
                                              "url": base_url}]}]


def alerts_card(alerts: list[dict], base_url: str = "") -> dict:
    blocks: list[dict] = [{"type": "header", "text": {"type": "plain_text", "text": f"🔔 Hospital Bid Radar 알림 {len(alerts)}건"}}]
    for a in alerts[:MAX_ITEMS]:
        label = ALERT_TYPES.get(a["alert_type"], a["alert_type"])
        mark = "🔴 " if a.get("severity") == "high" else ""
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text":
                       f"{mark}{ICON.get(a['alert_type'], '•')} *{label}* · {esc(a['title'], 150)}\n_{esc(a.get('message'))}_"}})
    if len(alerts) > MAX_ITEMS:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"외 {len(alerts) - MAX_ITEMS}건은 대시보드에서 확인하세요."}]})
    return {"text": f"Hospital Bid Radar 알림 {len(alerts)}건", "blocks": blocks + _link_block(base_url)}


def report_card(data: dict, base_url: str = "") -> dict:
    s = data["summary"]
    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": f"📡 Daily Report · {data['date']}"}},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*신규 입찰*\n{s['new_bids']}건"}, {"type": "mrkdwn", "text": f"*마감 임박*\n{s['closing']}건"},
            {"type": "mrkdwn", "text": f"*계약만료 예정(90일)*\n{s['expiring']}건"},
            {"type": "mrkdwn", "text": f"*경쟁사 신규 수주*\n{s['competitor_awards']}건"}]},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": "*Opportunity TOP 3*\n" + "\n".join(
            f"{t['rank']}. {esc(t['hospital'], 60)} — {t['score']}점 · {esc(t['reasons'], 160)}" for t in data["top"][:3])}}]
    if data.get("actions"):
        a = data["actions"][0]
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text":
                       f"*🤖 AI 추천 Action*\n{esc(a['hospital'], 60)}: " + ", ".join(esc(x, 80) for x in a["actions"][:3])}})
    return {"text": f"Hospital Bid Radar Daily Report {data['date']}", "blocks": blocks + _link_block(base_url)}


def send_card(webhook_url: str, card: dict, retries: int = 3, session=None) -> None:
    validate_webhook(webhook_url)
    post_with_retry(webhook_url, card, SlackError, "Slack", ok_codes=(200,), retries=retries, session=session)
