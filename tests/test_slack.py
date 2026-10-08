import json

import pytest

from hbr.alerts_dispatch import post_alerts_to_channel, post_alerts_to_slack
from hbr.analytics.alerts import generate_alerts
from hbr.config import get_settings
from hbr.notify.channels import CHANNELS
from hbr.notify.slack import SlackError, alerts_card, esc, report_card, send_card, validate_webhook
from hbr.reports.daily import build_for_user
from hbr.reports.mailer import post_daily_report_to_channel, post_daily_report_to_slack
from tests.conftest import TODAY

URL = "https://hooks.slack.com/services/T000/B000/SECRETTOKEN"


def settings(**kw):
    s = get_settings()
    return s.__class__(**{**s.__dict__, "slack_webhook_url": URL, "teams_webhook_url": "", **kw})


@pytest.mark.parametrize("url,ok", [
    (URL, True), ("http://hooks.slack.com/services/x", False), ("https://hooks.slack.com.evil.com/x", False),
    ("https://evil.com/hooks.slack.com", False), ("https://slack.com/api/chat.postMessage", False), ("", False)])
def test_validate_webhook(url, ok):
    if ok:
        assert validate_webhook(url) == url
    else:
        with pytest.raises(SlackError):
            validate_webhook(url)


def test_mrkdwn_injection_is_neutralized():
    evil = "<!channel> <https://evil.com|클릭> [링크](http://x) & 알부민"
    out = esc(evil)
    assert "<" not in out and ">" not in out and "[" not in out
    assert "&lt;!channel&gt;" in out and "&amp;" in out


def test_alerts_card_shape_and_cap():
    alerts = [{"alert_type": "CONTRACT_EXPIRY", "title": f"병원{i} <!here>", "message": "종료 D-30", "severity": "high"} for i in range(13)]
    card = alerts_card(alerts, "https://app.example.com")
    assert card["text"] and card["blocks"][0]["type"] == "header"
    sections = [b for b in card["blocks"] if b["type"] == "section"]
    assert len(sections) == 10 and "외 3건" in json.dumps(card["blocks"], ensure_ascii=False)
    assert all("<!here>" not in b["text"]["text"] for b in sections)
    assert card["blocks"][-1]["elements"][0]["url"] == "https://app.example.com"
    assert card["blocks"][-1]["type"] == "actions"
    assert all(b["type"] != "actions" for b in alerts_card(alerts, "http://insecure")["blocks"])
    assert len(card["blocks"]) <= 50                                    # Slack 블록 상한


def test_report_card(demo_repo):
    card = report_card(build_for_user(demo_repo, None, TODAY, briefing=False))
    assert len(card["blocks"][1]["fields"]) == 4 and all(len(f["text"]) <= 2000 for f in card["blocks"][1]["fields"])
    assert all(len(b["text"]["text"]) <= 3000 for b in card["blocks"] if b["type"] == "section" and "text" in b)


class Resp:
    def __init__(self, code):
        self.status_code = code


class Sess:
    def __init__(self, codes):
        self.codes, self.n = codes, 0

    def post(self, url, json, timeout):
        self.n += 1
        return Resp(self.codes[min(self.n - 1, len(self.codes) - 1)])


def test_send_retry_policy_and_secret_not_leaked(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    s = Sess([429, 500, 200])
    send_card(URL, {}, session=s)
    assert s.n == 3
    bad = Sess([404])
    with pytest.raises(SlackError) as e:
        send_card(URL, {}, session=bad)
    assert bad.n == 1 and "SECRETTOKEN" not in str(e.value)
    with pytest.raises(SlackError):
        send_card("https://evil.com/x", {}, session=Sess([200]))
    assert Sess([202]).codes == [202]
    with pytest.raises(SlackError):                                      # Slack 은 200 만 성공
        send_card(URL, {}, retries=1, session=Sess([202]))


def test_alerts_to_slack_idempotent_and_independent_from_teams(demo_repo):
    generate_alerts(demo_repo, TODAY)
    total = len(demo_repo.rows("alerts"))
    sent = []

    def boom(u, c):
        raise SlackError("HTTP 500")
    assert post_alerts_to_slack(demo_repo, settings(), sender=boom)["failed"] == total
    assert post_alerts_to_slack(demo_repo, settings(), sender=lambda u, c: sent.append(c))["slack"] == total
    assert post_alerts_to_slack(demo_repo, settings(), sender=lambda u, c: sent.append(c))["slack"] == 0
    assert len(sent) == 1
    # Teams 는 별개 표식 → Slack 게시 완료와 무관하게 아직 미게시
    both = settings(teams_webhook_url="https://x.logic.azure.com/y")
    assert post_alerts_to_channel(demo_repo, both, "teams", sender=lambda u, c: None)["teams"] == total
    assert {"slack", "teams"} <= set(demo_repo.rows("alerts")[0]["delivered_to"])
    assert post_alerts_to_slack(demo_repo, settings(slack_webhook_url=""))["skipped"] == "no webhook"


def test_daily_report_slack_once_per_day(demo_repo):
    calls = []
    assert post_daily_report_to_slack(demo_repo, settings(slack_webhook_url=""), TODAY) == "disabled"
    assert post_daily_report_to_channel(demo_repo, "slack", settings(), TODAY, sender=lambda u, c: calls.append(c)) == "sent"
    assert post_daily_report_to_slack(demo_repo, settings(), TODAY, sender=lambda u, c: calls.append(c)) == "skipped"
    assert len(calls) == 1
    assert {r["recipient"] for r in demo_repo.rows("email_reports")} == {"slack:channel"}


def test_registry_and_none_placeholder(monkeypatch):
    assert set(CHANNELS) == {"teams", "slack"} and all(c.label for c in CHANNELS.values())
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "none")
    assert get_settings().slack_webhook_url == ""
