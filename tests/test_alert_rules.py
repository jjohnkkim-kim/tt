from datetime import date

import pandas as pd

from hbr.analytics.alert_rules import Context, Rule, alert_matches, rule_from_row, rule_to_row, visible_alerts
from hbr.analytics.alerts import generate_alerts, recipients_for
from tests.conftest import TODAY

PRODUCTS = [{"id": 1, "name": "알파주", "product_group": "항체", "keywords": []}]


def alert(kind="NEW_BID", title="알파주 구매", hospital_id=1, **payload):
    return {"alert_type": kind, "hospital_id": hospital_id, "title": f"A병원 — {title}", "payload": {"title": title, **payload}}


def test_type_filter_and_deadline_days():
    r = Rule(types=("NEW_BID", "DEADLINE"), deadline_days=(3, 1))
    ctx = Context()
    assert alert_matches(r, alert("NEW_BID"), ctx) and not alert_matches(r, alert("FAILED"), ctx)
    assert alert_matches(r, alert("DEADLINE", days=3), ctx) and alert_matches(r, alert("DEADLINE", days=1), ctx)
    assert not alert_matches(r, alert("DEADLINE", days=7), ctx)                 # D-7 은 꺼 두었다


def test_scope_mine_is_product_or_watched_hospital_with_min_confidence():
    ctx = Context(products=PRODUCTS, watched={2})
    mine = Rule(scope="mine", min_match="MEDIUM")
    assert alert_matches(mine, alert(title="알파주 구매", hospital_id=9), ctx)           # 제품 매칭 (병원은 관심 병원 아님)
    assert alert_matches(mine, alert(title="다른 의약품", hospital_id=2), ctx)           # 관심 병원 (제품은 무관)
    assert not alert_matches(mine, alert(title="다른 의약품", hospital_id=9), ctx)       # 둘 다 아니면 제외
    group_only = alert(title="항체 의약품 구매", hospital_id=9)                           # 제품군만 일치 → LOW
    assert not alert_matches(mine, group_only, ctx)
    assert alert_matches(Rule(scope="mine", min_match="LOW"), group_only, ctx)           # 최소 신뢰도를 낮추면 포함
    assert alert_matches(Rule(scope="all"), alert(title="무관", hospital_id=9), Context())


def test_scope_mine_without_products_or_hospitals_receives_nothing():
    assert not alert_matches(Rule(scope="mine"), alert(title="알파주 구매"), Context())


def test_exclude_own_award_uses_the_recipients_company():
    a = alert("AWARD", title="의약품 단가", winner="가나제약(주)")
    assert not alert_matches(Rule(exclude_own=True), a, Context(own_aliases=["가나제약"]))
    assert alert_matches(Rule(exclude_own=False), a, Context(own_aliases=["가나제약"]))
    assert alert_matches(Rule(exclude_own=True), a, Context(own_aliases=["다라바이오"]))
    assert alert_matches(Rule(exclude_own=True), a, Context())                           # 회사 정보가 없으면 거르지 않는다


def test_legacy_competitor_award_rows_count_as_award_and_titles_fall_back():
    old = {"alert_type": "COMPETITOR_AWARD", "hospital_id": 1, "title": "가나제약 — A병원 수주", "payload": {}}
    assert alert_matches(Rule(), old, Context())
    assert not alert_matches(Rule(), old, Context(own_aliases=["가나제약"]))             # 예전 기록은 제목 앞부분을 낙찰업체로 본다


def test_rule_row_roundtrip_and_sanitizing():
    r = rule_from_row({"types": ["NEW_BID", "BOGUS"], "deadline_days": [1, 7, 7], "scope": "x", "min_match": "HIGH",
                       "exclude_own": False, "email_enabled": False})
    assert r.types == ("NEW_BID",) and r.deadline_days == (7, 1) and r.scope == "all" and r.min_match == "HIGH" and not r.exclude_own and not r.email_enabled
    assert rule_from_row(None) == Rule() and rule_from_row(rule_to_row(r)) == r


def test_repo_saves_one_rule_per_user_and_sanitizes(repo):
    u = repo.ensure_user("a@x.com", "a", "viewer")
    repo.save_alert_rule(u["id"], {"types": ["NEW_BID", "NOPE"], "deadline_days": [3, 99], "scope": "mine", "min_match": "ZZZ"})
    repo.save_alert_rule(u["id"], {"types": ["DEADLINE"], "deadline_days": [1], "scope": "all", "min_match": "HIGH", "email_enabled": False})
    rules = repo.rows("alert_rules")
    assert len(rules) == 1 and rules[0]["types"] == ["DEADLINE"] and rules[0]["deadline_days"] == [1] and rules[0]["email_enabled"] is False
    assert repo.get_alert_rule(u["id"])["min_match"] == "HIGH" and repo.get_alert_rule(999) is None


def test_legacy_recipients_ignore_new_types_but_deliver_awards_as_competitor_award():
    users = [{"id": 1, "is_active": True}]
    subs = [{"user_id": 1, "hospital_id": None, "alert_types": None}]                     # 예전 기본 구독
    assert recipients_for(alert("AWARD", winner="x"), users, subs) == users
    assert recipients_for(alert("DEADLINE", days=1), users, subs) == []                   # 새 종류는 예전 구독자에게 보내지 않는다
    assert recipients_for(alert("FAILED"), users, subs) == [] and recipients_for(alert("REBID"), users, subs) == []


# ── 이벤트 생성 ──────────────────────────────────────────────────────
def _hospital(repo):
    return repo.upsert_hospitals([{"name": "테스트병원", "name_norm": "테스트병원", "hospital_type": "병원", "is_active": True}])["테스트병원"]


def _bid(repo, hid, key, title, bid_date, deadline):
    repo.upsert("bids", [{"bid_key": key, "bid_ntce_no": key, "bid_ntce_ord": "000", "title": title, "hospital_id": hid, "inst_name": "테스트병원",
                          "bid_date": bid_date, "deadline": deadline, "budget": 1e8, "is_pharma": True, "product_tags": ["의약품(일반)"]}])


def test_deadline_alert_fires_once_per_threshold_with_closest_dday(repo):
    hid = _hospital(repo)
    _bid(repo, hid, "d7", "의약품 7일", "2026-10-01", "2026-10-15T10:00:00+09:00")        # D-7
    _bid(repo, hid, "d3", "의약품 3일", "2026-10-01", "2026-10-11T10:00:00+09:00")        # D-3
    _bid(repo, hid, "d2", "의약품 2일", "2026-10-01", "2026-10-10T10:00:00+09:00")        # D-2 → 가까운 기준 D-3
    _bid(repo, hid, "d0", "의약품 오늘", "2026-10-01", "2026-10-08T18:00:00+09:00")       # 오늘 마감 → D-1
    _bid(repo, hid, "d9", "의약품 9일", "2026-10-01", "2026-10-17T10:00:00+09:00")        # 7일 밖
    got = {a["dedup_key"]: a["payload"]["days"] for a in generate_alerts(repo, TODAY) if a["alert_type"] == "DEADLINE"}
    assert got == {"DL:d7:7": 7, "DL:d3:3": 3, "DL:d2:3": 3, "DL:d0:1": 1}
    assert [a for a in generate_alerts(repo, TODAY) if a["alert_type"] == "DEADLINE"] == []     # 같은 임계값은 한 번만


def test_failed_and_rebid_alerts_with_previous_link(repo):
    hid = _hospital(repo)
    repo.upsert("awards", [{"award_key": "f1", "bid_ntce_no": "OLD", "bid_ntce_ord": "000", "hospital_id": hid, "inst_name": "테스트병원",
                            "title": "의약품 단가계약", "result_status": "유찰", "award_date": "2026-10-06", "is_pharma": True, "product_tags": []}])
    _bid(repo, hid, "NEW", "(재공고)의약품 단가계약", "2026-10-07", "2026-10-20T10:00:00+09:00")
    kinds = {a["alert_type"]: a for a in generate_alerts(repo, TODAY)}
    assert "FAILED" in kinds and "REBID" in kinds and "NEW_BID" not in kinds             # 재공고는 신규 입찰과 따로 한 번만
    assert "이전 유찰" in kinds["REBID"]["message"] and "추정 연결" in kinds["REBID"]["message"]
    assert kinds["FAILED"]["payload"]["title"] == "의약품 단가계약"


def test_visible_alerts_follow_the_users_rule_and_company(repo):
    hid = _hospital(repo)
    _bid(repo, hid, "A", "알파주 구매", "2026-10-07", "2026-10-30T10:00:00+09:00")
    _bid(repo, hid, "B", "의약품 일반 구매", "2026-10-07", "2026-10-30T10:00:00+09:00")
    generate_alerts(repo, TODAY)
    mine, other = repo.create_company("가나"), repo.create_company("다라")
    repo.save_product(mine["id"], "알파주")
    repo.save_product(other["id"], "일반제품X")
    u1, u2 = repo.ensure_user("u1@x.com", "u1", "viewer"), repo.ensure_user("u2@x.com", "u2", "viewer")
    repo.assign_company(u1["id"], mine["id"])
    repo.assign_company(u2["id"], other["id"])
    for u in (u1, u2):
        repo.save_alert_rule(u["id"], {"types": ["NEW_BID"], "scope": "mine", "min_match": "MEDIUM"})
    titles = lambda u: sorted(a["payload"]["title"] for a in visible_alerts(repo, repo.get_user(u["email"]), days=36500))
    assert titles(u1) == ["알파주 구매"]                           # 내 제품만
    assert titles(u2) == []                                      # 다른 회사 제품(알파주)에 대한 알림은 보이지 않는다
    repo.save_alert_rule(u2["id"], {"types": ["NEW_BID"], "scope": "all"})
    assert titles(u2) == ["알파주 구매", "의약품 일반 구매"]


def test_dispatch_uses_rules_for_saved_users_and_legacy_subscriptions_for_the_rest(repo, monkeypatch):
    from hbr.alerts_dispatch import dispatch
    from hbr.config import get_settings

    hid = _hospital(repo)
    _bid(repo, hid, "A", "알파주 구매", "2026-10-07", "2026-10-30T10:00:00+09:00")
    _bid(repo, hid, "B", "의약품 일반 구매", "2026-10-07", "2026-10-30T10:00:00+09:00")
    generate_alerts(repo, TODAY)
    c = repo.create_company("가나")
    repo.save_product(c["id"], "알파주")
    ruled, quiet, legacy = (repo.ensure_user(f"{n}@x.com", n, "viewer") for n in ("ruled", "quiet", "legacy"))
    for u in (ruled, quiet):
        repo.assign_company(u["id"], c["id"])
    repo.save_alert_rule(ruled["id"], {"types": ["NEW_BID"], "scope": "mine", "min_match": "MEDIUM", "email_enabled": True})
    repo.save_alert_rule(quiet["id"], {"types": ["NEW_BID"], "scope": "all", "email_enabled": False})        # 이메일 끔
    repo.upsert("subscriptions", [{"user_id": legacy["id"], "hospital_id": None, "alert_types": None, "channel": "email"}])
    sent = []
    import hbr.alerts_dispatch as d

    monkeypatch.setattr(d, "send_email", lambda settings, to, subject, html, text="": sent.append((to, text)) or "dry_run")
    res = dispatch(repo, get_settings())
    by_to = {to: text for to, text in sent}
    assert "ruled@x.com" in by_to and "알파주 구매" in by_to["ruled@x.com"] and "의약품 일반 구매" not in by_to["ruled@x.com"]
    assert "quiet@x.com" not in by_to                                                    # 이메일을 끈 사용자
    assert "legacy@x.com" in by_to and "알파주 구매" in by_to["legacy@x.com"]            # 예전 구독 방식은 그대로(신규 입찰 모두)
    assert res["failed"] == 0


# ── 화면 ────────────────────────────────────────────────────────────
def _run(page, user):
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / f"views/{page}.py"), default_timeout=90)
    at.session_state["user"] = user
    return at.run()


def test_alerts_page_lists_events_for_the_logged_in_user_and_respects_the_rule():
    import streamlit as st

    from hbr.auth.rbac import User
    from views._common import repo

    st.cache_data.clear()
    r = repo()
    generate_alerts(r, TODAY)
    row = r.ensure_user("alertpage@x.com", "ap", "viewer")
    u = User(row["id"], "alertpage@x.com", "ap", "viewer")
    all_alerts = _run("alerts", u)
    assert not all_alerts.exception, [e.value for e in all_alerts.exception]
    assert any("hbr-bid" in m.value for m in all_alerts.markdown)               # 기본 조건(전체)이라 이벤트가 보인다
    r.save_alert_rule(row["id"], {"types": [], "scope": "all"})                  # 모든 종류를 끄면 아무것도 안 보인다
    none = _run("alerts", u)
    assert not none.exception and not any("hbr-bid" in m.value for m in none.markdown)
    assert any("조건에 맞는 알림이 아직 없습니다" in m.value for m in none.markdown)


def test_settings_alert_tab_saves_a_rule():
    from hbr.auth.rbac import User
    from views._common import repo

    r = repo()
    row = r.ensure_user("ruleform@x.com", "rf", "admin")
    u = User(row["id"], "ruleform@x.com", "rf", "admin")
    at = _run("settings", u)
    assert not at.exception, [e.value for e in at.exception]
    assert r.get_alert_rule(row["id"]) is None
    at.button(key="alert_save").click().run()
    saved = r.get_alert_rule(row["id"])
    assert saved and saved["scope"] == "all" and "NEW_BID" in saved["types"] and saved["deadline_days"] == [7, 3, 1]
