import pytest

from hbr.alerts_dispatch import post_alerts_to_kakao
from hbr.analytics.alerts import generate_alerts
from hbr.config import get_settings
from hbr.notify.kakao import (KakaoError, SolapiProvider, alert_variables, mask_phone, normalize_phone,
                              report_variables, TEMPLATE_ALERT, TEMPLATE_REPORT)
from hbr.reports.daily import build_for_user
from hbr.reports.mailer import send_daily_kakao
from tests.conftest import TODAY


def settings(**kw):
    s = get_settings()
    base = dict(solapi_api_key="KEY", solapi_api_secret="SECRET", kakao_pf_id="PF", kakao_sender="0212345678",
                kakao_tpl_alert="TPL_A", kakao_tpl_report="TPL_R")
    return s.__class__(**{**s.__dict__, **base, **kw})


@pytest.mark.parametrize("raw,expected", [
    ("010-1234-5678", "01012345678"), ("+82 10-1234-5678", "01012345678"), ("01012345678", "01012345678"),
    ("011-123-4567", "0111234567"), ("02-123-4567", None), ("010-12-345", None), ("", None), (None, None), ("abc", None)])
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


def test_mask_phone():
    assert mask_phone("01012345678") == "010****5678"


def test_variables_are_short_and_complete():
    alerts = [{"title": "서울대학교병원 [피싱](http://x) " + "가" * 100, "message": "예산 5억원 " + "나" * 300}] * 3
    v = alert_variables(alerts)
    assert v["#{건수}"] == "3" and len(v["#{제목}"]) <= 40 and len(v["#{내용}"]) <= 100 and "[" not in v["#{제목}"]
    for key in v:                                              # 템플릿 본문의 변수와 일치해야 승인된 템플릿에 채워짐
        assert key in TEMPLATE_ALERT


def test_report_variables_match_template(demo_repo):
    v = report_variables(build_for_user(demo_repo, None, TODAY, briefing=False))
    assert all(k in TEMPLATE_REPORT for k in v) and all(k in v for k in
                                                         ["#{날짜}", "#{신규입찰}", "#{마감임박}", "#{계약만료}", "#{경쟁사수주}"])


class Resp:
    def __init__(self, code):
        self.status_code = code


class Sess:
    def __init__(self, codes):
        self.codes, self.calls = codes, []

    def post(self, url, json, headers, timeout):
        self.calls.append((url, json, headers))
        return Resp(self.codes[min(len(self.calls) - 1, len(self.codes) - 1)])


def test_solapi_request_shape_and_hmac():
    import hashlib
    import hmac as hm
    import re

    sess = Sess([200])
    SolapiProvider("KEY", "SECRET", "PF", "02-1234-5678", session=sess).send("010-1234-5678", "TPL", {"#{건수}": "1"})
    url, body, headers = sess.calls[0]
    m = re.match(r"HMAC-SHA256 apiKey=KEY, date=(\S+), salt=(\w+), signature=(\w+)", headers["Authorization"])
    assert m and m.group(3) == hm.new(b"SECRET", (m.group(1) + m.group(2)).encode(), hashlib.sha256).hexdigest()
    assert body["message"]["to"] == "01012345678" and body["message"]["from"] == "0212345678"
    assert body["message"]["kakaoOptions"] == {"pfId": "PF", "templateId": "TPL", "variables": {"#{건수}": "1"}}


def test_solapi_errors_do_not_leak_secrets_or_phone(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    p = SolapiProvider("KEY", "SECRET", "PF", "0212345678", session=Sess([401]))
    with pytest.raises(KakaoError) as e:
        p.send("01012345678", "T", {})
    msg = str(e.value)
    assert "01012345678" not in msg and "010****5678" in msg and "SECRET" not in msg and len(p.http.calls) == 1   # 4xx 재시도 없음
    p5 = SolapiProvider("KEY", "SECRET", "PF", "0212345678", session=Sess([500, 500, 200]))
    p5.send("01012345678", "T", {})
    assert len(p5.http.calls) == 3
    with pytest.raises(KakaoError):
        SolapiProvider("K", "S", "PF", "0212345678", session=Sess([200])).send("02-123-4567", "T", {})     # 휴대폰 아님


class FakeProvider:
    def __init__(self, fail_for=()):
        self.sent, self.fail_for = [], set(fail_for)

    def send(self, to, template_id, variables):
        if to in self.fail_for:
            raise KakaoError("fail")
        self.sent.append((to, template_id, variables))


def _users(repo):
    a = repo.ensure_user("a@x.com", "A", "sales")
    b = repo.ensure_user("b@x.com", "B", "sales")
    c = repo.ensure_user("c@x.com", "C", "sales")
    repo.update("users", {"phone": "01011112222", "kakao_opt_in": True}, [("id", "eq", a["id"])])
    repo.update("users", {"phone": "01033334444", "kakao_opt_in": True}, [("id", "eq", b["id"])])
    repo.update("users", {"phone": "01055556666", "kakao_opt_in": False}, [("id", "eq", c["id"])])     # 미동의
    for u in (a, b, c):
        repo.insert("subscriptions", [{"user_id": u["id"], "hospital_id": None, "alert_types": None}])
    return a, b, c


def test_alerts_only_to_opted_in_users_and_idempotent(demo_repo):
    _users(demo_repo)
    generate_alerts(demo_repo, TODAY)
    prov = FakeProvider()
    res = post_alerts_to_kakao(demo_repo, settings(), provider=prov)
    assert res == {"kakao": 2, "failed": 0}
    assert {t for t, _, _ in prov.sent} == {"01011112222", "01033334444"}      # 미동의 사용자 제외
    assert all(tpl == "TPL_A" for _, tpl, _ in prov.sent)
    assert post_alerts_to_kakao(demo_repo, settings(), provider=prov)["kakao"] == 0       # 재실행해도 중복 발송 없음
    assert len(prov.sent) == 2


def test_alert_failure_is_retried_per_user(demo_repo):
    a, b, _ = _users(demo_repo)
    generate_alerts(demo_repo, TODAY)
    res = post_alerts_to_kakao(demo_repo, settings(), provider=FakeProvider(fail_for={"01011112222"}))
    assert res == {"kakao": 1, "failed": 1}
    ok = FakeProvider()
    assert post_alerts_to_kakao(demo_repo, settings(), provider=ok)["kakao"] == 1               # 실패한 A 만 재시도
    assert [t for t, _, _ in ok.sent] == ["01011112222"]


def test_subscription_scope_respected(demo_repo):
    a = demo_repo.ensure_user("a@x.com", "A", "sales")
    demo_repo.update("users", {"phone": "01011112222", "kakao_opt_in": True}, [("id", "eq", a["id"])])
    demo_repo.insert("subscriptions", [{"user_id": a["id"], "hospital_id": 99999, "alert_types": None}])   # 존재하지 않는 병원
    generate_alerts(demo_repo, TODAY)
    assert post_alerts_to_kakao(demo_repo, settings(), provider=FakeProvider())["kakao"] == 0


def test_disabled_without_config_or_template(demo_repo):
    _users(demo_repo)
    generate_alerts(demo_repo, TODAY)
    assert post_alerts_to_kakao(demo_repo, settings(solapi_api_key=""))["skipped"] == "not configured"
    assert post_alerts_to_kakao(demo_repo, settings(kakao_tpl_alert=""), provider=FakeProvider())["skipped"] == "no template"
    assert send_daily_kakao(demo_repo, settings(solapi_api_key=""), TODAY)["disabled"]


def test_daily_kakao_idempotent_without_storing_phone(demo_repo):
    a, b, c = _users(demo_repo)
    demo_repo.update("users", {"report_enabled": False}, [("id", "eq", b["id"])])              # 리포트 수신 해제
    prov = FakeProvider()
    assert send_daily_kakao(demo_repo, settings(), TODAY, provider=prov) == {"sent": 1, "failed": 0, "skipped": 0}
    assert send_daily_kakao(demo_repo, settings(), TODAY, provider=prov) == {"sent": 0, "failed": 0, "skipped": 1}
    rows = demo_repo.rows("email_reports")
    assert [r["recipient"] for r in rows] == [f"kakao:user{a['id']}"]
    assert "0101111" not in str(rows)                                                           # 휴대폰번호 미저장
    bad = FakeProvider(fail_for={"01011112222"})
    d2 = TODAY.replace(day=9)
    assert send_daily_kakao(demo_repo, settings(), d2, provider=bad)["failed"] == 1
    assert send_daily_kakao(demo_repo, settings(), d2, provider=prov)["sent"] == 1               # 실패 후 재시도


def test_kakao_enabled_flag():
    assert settings().kakao_enabled and not settings(kakao_sender="").kakao_enabled
