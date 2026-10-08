import json

import pytest

from hbr.alerts_dispatch import post_alerts_to_teams
from hbr.analytics.alerts import generate_alerts
from hbr.config import get_settings
from hbr.notify.teams import TeamsError, alerts_card, report_card, send_card, validate_webhook
from hbr.reports.daily import build_for_user
from hbr.reports.mailer import post_daily_report_to_teams
from tests.conftest import TODAY

URL = "https://prod-12.koreacentral.logic.azure.com:443/workflows/abc/triggers/manual/paths/invoke?sig=SECRET"


def settings(**kw):
    s = get_settings()
    return s.__class__(**{**s.__dict__, "teams_webhook_url": URL, **kw})


@pytest.mark.parametrize("url,ok", [
    (URL, True), ("https://contoso.webhook.office.com/webhookb2/x", True),
    ("http://prod.logic.azure.com/x", False), ("https://evil.example.com/hook", False),
    ("https://logic.azure.com.evil.com/x", False), ("", False), ("not a url", False)])
def test_validate_webhook(url, ok):
    if ok:
        assert validate_webhook(url) == url
    else:
        with pytest.raises(TeamsError):
            validate_webhook(url)


def test_alerts_card_shape_caps_items_and_strips_links():
    alerts = [{"alert_type": "NEW_BID", "title": f"병원{i} [피싱](http://evil) 알부민", "message": "예산 5억원", "severity": "high"}
              for i in range(13)]
    card = alerts_card(alerts, "https://app.example.com")
    c = card["attachments"][0]["content"]
    assert card["attachments"][0]["contentType"] == "application/vnd.microsoft.card.adaptive" and c["version"] == "1.4"
    containers = [b for b in c["body"] if b["type"] == "Container"]
    assert len(containers) == 10 and "외 3건" in c["body"][-1]["text"]
    texts = [i["text"] for ct in containers for i in ct["items"]]
    assert all("[" not in t and "]" not in t for t in texts)               # Markdown 링크 문법 제거
    assert c["actions"][0]["url"] == "https://app.example.com"
    assert "actions" not in alerts_card(alerts, "http://insecure")["attachments"][0]["content"]


def test_report_card(demo_repo):
    data = build_for_user(demo_repo, None, TODAY, briefing=False)
    body = report_card(data)["attachments"][0]["content"]["body"]
    assert any(b["type"] == "FactSet" and len(b["facts"]) == 4 for b in body)


class Resp:
    def __init__(self, code):
        self.status_code = code


class Sess:
    def __init__(self, codes):
        self.codes, self.n = codes, 0

    def post(self, url, json, timeout):
        self.n += 1
        return Resp(self.codes[min(self.n - 1, len(self.codes) - 1)])


def test_send_card_retries_5xx_but_not_4xx(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    s = Sess([502, 502, 202])
    send_card(URL, {}, session=s)
    assert s.n == 3
    bad = Sess([400])
    with pytest.raises(TeamsError) as e:
        send_card(URL, {}, session=bad)
    assert bad.n == 1 and "SECRET" not in str(e.value)           # URL(비밀) 은 오류 메시지에 노출 금지
    with pytest.raises(TeamsError):
        send_card("https://evil.example.com/x", {}, session=Sess([200]))


def test_post_alerts_to_teams_is_idempotent_and_retries_failures(demo_repo):
    generate_alerts(demo_repo, TODAY)
    total = len(demo_repo.rows("alerts"))
    sent = []

    def ok(url, card):
        sent.append(card)

    def boom(url, card):
        raise TeamsError("HTTP 500")
    assert post_alerts_to_teams(demo_repo, settings(), sender=boom)["failed"] == total
    assert all("teams" not in (a["delivered_to"] or []) for a in demo_repo.rows("alerts"))     # 실패 → 미표시
    assert post_alerts_to_teams(demo_repo, settings(), sender=ok)["teams"] == total
    assert post_alerts_to_teams(demo_repo, settings(), sender=ok)["teams"] == 0                 # 재실행해도 중복 게시 없음
    assert len(sent) == 1
    assert post_alerts_to_teams(demo_repo, settings(teams_webhook_url=""))["skipped"] == "no webhook"


def test_teams_independent_of_email_dispatch(demo_repo):
    from hbr.alerts_dispatch import dispatch

    u = demo_repo.ensure_user("s@x.com", "영업", "sales")
    demo_repo.insert("subscriptions", [{"user_id": u["id"], "hospital_id": None, "alert_types": None}])
    generate_alerts(demo_repo, TODAY)
    dispatch(demo_repo, get_settings())
    n = post_alerts_to_teams(demo_repo, settings(), sender=lambda u, c: None)["teams"]
    assert n == len(demo_repo.rows("alerts")) > 0            # 이메일 발송 완료 여부와 무관하게 게시


def test_daily_report_teams_once_per_day(demo_repo):
    calls = []
    assert post_daily_report_to_teams(demo_repo, settings(teams_webhook_url=""), TODAY) == "disabled"
    assert post_daily_report_to_teams(demo_repo, settings(), TODAY, sender=lambda u, c: calls.append(c)) == "sent"
    assert post_daily_report_to_teams(demo_repo, settings(), TODAY, sender=lambda u, c: calls.append(c)) == "skipped"
    assert len(calls) == 1

    def boom(u, c):
        raise TeamsError("HTTP 500")
    assert post_daily_report_to_teams(demo_repo, settings(), date_(2), sender=boom) == "failed"
    assert post_daily_report_to_teams(demo_repo, settings(), date_(2), sender=lambda u, c: None) == "sent"   # 실패 후 재시도


def date_(d):
    from datetime import date
    return date(2026, 10, d)


def test_none_placeholder_disables(monkeypatch):
    monkeypatch.setenv("TEAMS_WEBHOOK_URL", "none")
    assert get_settings().teams_webhook_url == ""
