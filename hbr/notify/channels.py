"""웹훅 채널 레지스트리: 채널을 추가하려면 여기에 한 줄 등록 (dispatch·리포트·설정 화면이 공통 사용)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import slack, teams


@dataclass(frozen=True)
class Channel:
    name: str                       # delivered_to 표식 / email_reports 키 접두사
    label: str
    url: Callable                   # Settings → webhook URL ('' 이면 비활성)
    alerts_card: Callable
    report_card: Callable
    send: Callable                  # (url, card)
    error: type


CHANNELS = {
    "teams": Channel("teams", "Teams", lambda s: s.teams_webhook_url, teams.alerts_card, teams.report_card,
                     teams.send_card, teams.TeamsError),
    "slack": Channel("slack", "Slack", lambda s: s.slack_webhook_url, slack.alerts_card, slack.report_card,
                     slack.send_card, slack.SlackError),
}
