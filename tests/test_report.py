from datetime import date

from hbr.config import get_settings
from hbr.reports.daily import build_for_user, render_html, render_text
from hbr.reports.mailer import recipient_addresses, send_daily_reports
from tests.conftest import TODAY


def test_report_has_all_sections_and_top10(demo_repo):
    data = build_for_user(demo_repo, None, TODAY, briefing=False)
    html = render_html(data, "http://app")
    for h in ["1. 신규 입찰 현황", "2. 마감 임박 입찰", "3. 계약 만료 예정", "4. 경쟁사 신규 수주",
              "5. Opportunity TOP 10", "6. AI 추천 Action", "7. 병원별 주요 이슈"]:
        assert h in html
    assert len(data["top"]) == 10 and data["actions"] and "http://app" in html
    assert "Daily Report" in render_text(data)


def test_report_escapes_html(demo_repo):
    demo_repo.upsert("bids", [{"bid_key": "xss", "bid_ntce_no": "xss", "title": "<script>alert(1)</script> 의약품",
                               "hospital_id": 1, "inst_name": "x", "bid_date": TODAY.isoformat(), "budget": 1e8,
                               "deadline": "2026-10-12T10:00:00+09:00", "is_pharma": True, "product_tags": []}])
    html = render_html(build_for_user(demo_repo, None, TODAY, briefing=False))
    assert "<script>alert(1)" not in html and "&lt;script&gt;" in html


def test_monday_lookback_covers_weekend():
    from hbr.reports.daily import _lookback

    assert _lookback(date(2026, 10, 5)) == 3 and _lookback(date(2026, 10, 8)) == 1   # 월요일 / 목요일


def test_watched_hospitals_marked(demo_repo):
    u = demo_repo.ensure_user("s@x.com", "영업", "sales")
    demo_repo.add_watch(u["id"], 1)
    html = render_html(build_for_user(demo_repo, u, TODAY, briefing=False))
    assert "★" in html and "영업님을 위한" in html


def test_send_daily_reports_is_idempotent(demo_repo, tmp_path):
    u = demo_repo.ensure_user("s@x.com", "영업", "sales")
    demo_repo.update("users", {"personal_email": "me@gmail.com"}, [("id", "eq", u["id"])])
    s = get_settings()
    assert recipient_addresses(demo_repo.get_user("s@x.com")) == ["s@x.com", "me@gmail.com"]
    first = send_daily_reports(demo_repo, s, TODAY, briefing=False)
    assert first == {"sent": 2, "failed": 0, "skipped": 0}
    again = send_daily_reports(demo_repo, s, TODAY, briefing=False)
    assert again == {"sent": 0, "failed": 0, "skipped": 2}
    rows = demo_repo.rows("email_reports")
    assert {r["status"] for r in rows} == {"dry_run"} and "Daily Report" in rows[0]["subject"]


def test_disabled_users_get_no_report(demo_repo):
    u = demo_repo.ensure_user("s@x.com", "영업", "sales")
    demo_repo.update("users", {"report_enabled": False}, [("id", "eq", u["id"])])
    assert send_daily_reports(demo_repo, get_settings(), TODAY, briefing=False)["sent"] == 0
    assert not [r for r in demo_repo.rows("email_reports") if r["recipient"] == "s@x.com"]


def test_failed_send_is_recorded_and_retried(demo_repo, monkeypatch):
    import hbr.reports.mailer as m

    demo_repo.ensure_user("s@x.com", "영업", "sales")
    monkeypatch.setattr(m, "send_email", lambda *a, **k: (_ for _ in ()).throw(m.MailError("smtp down")))
    st = send_daily_reports(demo_repo, get_settings(), TODAY, briefing=False)
    assert st["failed"] >= 1 and demo_repo.rows("email_reports")[0]["status"] == "failed"
    monkeypatch.setattr(m, "send_email", lambda *a, **k: "sent")
    st = send_daily_reports(demo_repo, get_settings(), TODAY, briefing=False)
    assert st["sent"] >= 1 and demo_repo.rows("email_reports")[0]["status"] == "sent"


def test_instant_alert_dispatch(demo_repo):
    from hbr.alerts_dispatch import dispatch
    from hbr.analytics.alerts import generate_alerts

    u = demo_repo.ensure_user("s@x.com", "영업", "sales")
    demo_repo.insert("subscriptions", [{"user_id": u["id"], "hospital_id": None, "alert_types": None}])
    generate_alerts(demo_repo, TODAY)
    res = dispatch(demo_repo, get_settings())
    assert res["alerts"] > 0 and res["emails"] == 1 and res["failed"] == 0
    assert dispatch(demo_repo, get_settings())["alerts"] == 0        # 발송 완료 처리


def test_report_builds_in_bids_only_state(repo):
    """낙찰·계약 수집 전(입찰공고만 모드)에도 리포트가 만들어져야 한다."""
    repo.upsert("hospitals", [{"name": "테스트병원", "name_norm": "테스트병원", "hospital_type": "병원", "is_active": True}])
    hid = repo.hospital_id_by_name("테스트병원")
    repo.upsert("bids", [{"bid_key": "b1", "bid_ntce_no": "b1", "bid_ntce_ord": "000", "title": "[의약품] 구매",
                          "hospital_id": hid, "inst_name": "테스트병원", "bid_date": TODAY.isoformat(), "budget": 1e8,
                          "deadline": "2026-10-12T10:00:00+09:00", "is_pharma": True, "product_tags": ["의약품(일반)"]}])
    data = build_for_user(repo, {"id": -1, "name": "t"}, TODAY, briefing=False)
    assert data["summary"]["new_bids"] == 1 and data["summary"]["competitor_awards"] == 0 and data["summary"]["expiring"] == 0
    assert "Daily Report" in render_text(data) and "테스트병원" in render_html(data)
