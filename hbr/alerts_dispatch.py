"""즉시 알림 발송: 미발송 알림 → 구독자별 요약 메일."""
from __future__ import annotations

from collections import defaultdict

from .analytics.alerts import recipients_for
from .config import Settings
from .constants import ALERT_TYPES
from .reports.mailer import MailError, recipient_addresses, send_email
from .store.repo import Repo
from .utils import now_kst


def _render(alerts: list[dict], base_url: str) -> tuple[str, str]:
    from html import escape

    rows = "".join(
        f"<tr><td style='padding:8px;border-bottom:1px solid #eee;'><b>[{escape(ALERT_TYPES.get(a['alert_type'], a['alert_type']))}]</b> "
        f"{escape(a['title'])}<br><span style='color:#55637a;font-size:12px;'>{escape(a.get('message') or '')}</span></td></tr>"
        for a in alerts)
    html = (f"<div style='font-family:Malgun Gothic,Arial;max-width:640px'><h3>🔔 Hospital Bid Radar 알림 {len(alerts)}건</h3>"
            f"<table width='100%' style='border-collapse:collapse'>{rows}</table>"
            f"<p><a href='{escape(base_url)}'>대시보드 열기</a></p></div>")
    text = "\n".join(f"[{ALERT_TYPES.get(a['alert_type'])}] {a['title']} — {a.get('message', '')}" for a in alerts)
    return html, text


def dispatch(repo: Repo, settings: Settings, limit: int = 200) -> dict:
    pending = [a for a in repo.rows("alerts", [("dispatched_at", "isnull", True)], order="id", limit=limit)]
    if not pending:
        return {"alerts": 0, "emails": 0, "failed": 0}
    users = repo.rows("users", [("is_active", "eq", True)])
    subs = repo.rows("subscriptions")
    own_by_company = {cid: repo.own_aliases(cid) for cid in {u.get("company_id") for u in users} if cid}
    per_user: dict[int, list[dict]] = defaultdict(list)
    by_id = {u["id"]: u for u in users}
    for a in pending:
        for u in recipients_for(a, users, subs, own_by_company):
            per_user[u["id"]].append(a)
    emails = failed = 0
    failed_users: set[int] = set()
    for uid, alerts in per_user.items():
        html, text = _render(alerts, settings.app_base_url)
        subject = f"[Hospital Bid Radar] 알림 {len(alerts)}건 — {alerts[0]['title'][:40]}"
        for addr in recipient_addresses(by_id[uid]):
            try:
                send_email(settings, addr, subject, html, text)
                emails += 1
            except MailError:
                failed += 1
                failed_users.add(uid)
    # 실패한 수신자가 있는 알림은 다음 주기에 재시도 (수신자 없는 알림은 완료 처리)
    retry_ids = {a["id"] for uid in failed_users for a in per_user[uid]}
    now = now_kst().isoformat()
    for a in pending:
        if a["id"] not in retry_ids:
            repo.update("alerts", {"dispatched_at": now}, [("id", "eq", a["id"])])
    return {"alerts": len(pending), "emails": emails, "failed": failed}
