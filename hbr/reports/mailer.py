"""메일 발송: SMTP(STARTTLS) 또는 Dry-run(파일 저장). 발송 이력은 email_reports 에 기록."""
from __future__ import annotations

import logging
import smtplib
import time
from datetime import date
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from pathlib import Path

from ..config import Settings, get_settings
from ..store.repo import Repo
from ..utils import now_kst

log = logging.getLogger(__name__)
OUTBOX = Path("outbox")


class MailError(RuntimeError):
    pass


def build_message(settings: Settings, to: str, subject: str, html: str, text: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    name, addr = parseaddr(settings.mail_from)
    msg["From"] = formataddr((name, addr)) if addr else settings.mail_from
    msg["To"] = to
    msg.set_content(text or "HTML 메일을 지원하는 클라이언트에서 확인하세요.")
    msg.add_alternative(html, subtype="html")
    return msg


def send_email(settings: Settings, to: str, subject: str, html: str, text: str = "",
               retries: int = 3) -> str:
    """성공 시 'sent' 또는 'dry_run'. 실패 시 MailError."""
    if settings.mail_dry_run or not settings.smtp_user:
        OUTBOX.mkdir(exist_ok=True)
        safe = "".join(c if c.isalnum() else "_" for c in f"{now_kst():%Y%m%d_%H%M%S}_{to}")
        (OUTBOX / f"{safe}.html").write_text(f"<!-- To: {to}\n Subject: {subject} -->\n{html}", encoding="utf-8")
        return "dry_run"
    msg = build_message(settings, to, subject, html, text)
    last = None
    for attempt in range(retries):
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as s:
                s.starttls()
                s.login(settings.smtp_user, settings.smtp_password)
                s.send_message(msg)
            return "sent"
        except (smtplib.SMTPException, OSError) as e:
            last = e
            time.sleep(2 ** attempt)
    raise MailError(str(last))


def recipient_addresses(user: dict) -> list[str]:
    """회사 메일 + 개인 메일 (중복 제거)."""
    out: list[str] = []
    for a in (user.get("email"), user.get("personal_email")):
        if a and a.lower() not in out:
            out.append(a.lower())
    return out


def send_daily_reports(repo: Repo, settings: Settings | None = None, today: date | None = None,
                       briefing: bool = True) -> dict:
    """수신 설정한 모든 사용자에게 개인화 리포트 발송. 같은 날·같은 주소로는 중복 발송하지 않는다(멱등)."""
    from ..utils import today_kst
    from .daily import build_for_user, render_html, render_text

    settings, today = settings or get_settings(), today or today_kst()
    done = {(r["recipient"]) for r in repo.rows("email_reports", [("report_date", "eq", today.isoformat()),
                                                                  ("status", "in", ["sent", "dry_run"])])}
    stats = {"sent": 0, "failed": 0, "skipped": 0}
    for user in repo.rows("users", [("is_active", "eq", True), ("report_enabled", "eq", True)]):
        data = build_for_user(repo, user, today, briefing)
        html, text = render_html(data, settings.app_base_url), render_text(data)
        subject = settings.report_subject.format(date=today.isoformat())
        for addr in recipient_addresses(user):
            if addr in done:
                stats["skipped"] += 1
                continue
            row = {"report_date": today.isoformat(), "user_id": user["id"], "recipient": addr,
                   "subject": subject, "body_html": html, "summary": data["summary"]}
            try:
                row["status"] = send_email(settings, addr, subject, html, text)
                row["sent_at"] = now_kst().isoformat()
                stats["sent"] += 1
            except MailError as e:
                row.update(status="failed", error=str(e)[:500])
                stats["failed"] += 1
            repo.upsert("email_reports", [row])
    return stats


def post_daily_report_to_channel(repo: Repo, channel: str, settings: Settings | None = None,
                                 today: date | None = None, sender=None) -> str:
    """Daily Report 요약 카드를 채널(Teams/Slack)에 하루 1회 게시 (email_reports 에 '<채널>:channel' 로 멱등 기록)."""
    from ..notify.channels import CHANNELS
    from ..utils import today_kst
    from .daily import build_for_user

    ch, settings, today = CHANNELS[channel], settings or get_settings(), today or today_kst()
    url = ch.url(settings)
    if not url:
        return "disabled"
    key = f"{channel}:channel"
    if repo.rows("email_reports", [("report_date", "eq", today.isoformat()), ("recipient", "eq", key),
                                    ("status", "eq", "sent")]):
        return "skipped"
    data = build_for_user(repo, None, today, briefing=False)
    row = {"report_date": today.isoformat(), "recipient": key, "subject": f"{ch.label} Daily Report {today}",
           "summary": data["summary"]}
    try:
        (sender or ch.send)(url, ch.report_card(data, settings.app_base_url))
        row.update(status="sent", sent_at=now_kst().isoformat())
    except ch.error as e:
        row.update(status="failed", error=str(e)[:500])
    repo.upsert("email_reports", [row])
    return row["status"]


def post_daily_report_to_teams(repo: Repo, settings: Settings | None = None, today: date | None = None,
                               sender=None) -> str:
    return post_daily_report_to_channel(repo, "teams", settings, today, sender)


def post_daily_report_to_slack(repo: Repo, settings: Settings | None = None, today: date | None = None,
                               sender=None) -> str:
    return post_daily_report_to_channel(repo, "slack", settings, today, sender)
