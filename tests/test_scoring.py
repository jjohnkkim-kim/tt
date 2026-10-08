from datetime import date

import pytest

from hbr.analytics.actions import recommend_actions
from hbr.analytics.alerts import generate_alerts, recipients_for
from hbr.analytics.data import load_snapshot
from hbr.analytics.scoring import (compute_opportunities, competition_score, expiry_score, frequency_score,
                                   market_scores, pattern_score)
from hbr.constants import SCORE_WEIGHTS
from tests.conftest import TODAY


def test_weights_sum_to_one():
    assert sum(SCORE_WEIGHTS.values()) == pytest.approx(1.0)


@pytest.mark.parametrize("days,expected", [(None, 25), (-10, 70), (-200, 30), (0, 100), (30, 100), (31, 92), (60, 92),
                                           (61, 82), (90, 82), (91, 60), (180, 60), (181, 35), (365, 35), (400, 15)])
def test_expiry_score(days, expected):
    assert expiry_score(days) == expected


def test_component_scores_monotonic():
    assert [competition_score(n) for n in range(0, 6)] == [30, 45, 70, 90, 100, 100]
    assert pattern_score(3, False, True) > pattern_score(2, False, True) > pattern_score(1, False, True) > pattern_score(0, False, True)
    assert frequency_score(0) == 0 and frequency_score(3) == 50 and frequency_score(99) == 100
    ms = market_scores({1: 1e9, 2: 1e8, 3: 0})
    assert ms[1] == pytest.approx(100) and ms[1] > ms[2] > ms[3] == 0
    assert market_scores({}) == {} and market_scores({1: 0}) == {1: 0.0}


def _add(repo, **kw):
    hid = repo.upsert_hospitals([{"name": "테스트병원", "name_norm": "테스트병원", "hospital_type": "병원"}])["테스트병원"]
    return hid


def test_scores_use_only_pharma_rows(repo):
    hid = _add(repo)
    # 비의약품 계약만 있는 병원 → 점수 대상 아님
    repo.upsert("contracts", [{"contract_key": "x", "contract_no": "x", "hospital_id": hid, "inst_name": "테스트병원",
                               "end_date": "2026-10-20", "contract_date": "2026-01-01", "contract_amount": 1e9,
                               "is_pharma": False, "end_date_estimated": False}])
    assert compute_opportunities(load_snapshot(repo), TODAY) == []


def test_imminent_expiry_with_competitor_streak_scores_high(repo):
    hid = _add(repo)
    gc = next(c for c in repo.competitor_index() if c["name"] == "GC")
    repo.upsert("contracts", [{"contract_key": "c", "contract_no": "c", "hospital_id": hid, "inst_name": "테스트병원",
                               "end_date": "2026-12-26", "contract_date": "2025-12-27", "contract_amount": 5e8,
                               "is_pharma": True, "end_date_estimated": False, "vendor_name": "GC녹십자", "competitor_id": gc["id"]}])
    repo.upsert("awards", [{"award_key": f"a{i}", "bid_ntce_no": f"a{i}", "hospital_id": hid, "inst_name": "테스트병원",
                            "winner_name": "GC녹십자", "competitor_id": gc["id"], "award_amount": 3e8,
                            "award_date": f"2026-0{i}-01", "is_pharma": True} for i in (3, 6, 9)])
    o = compute_opportunities(load_snapshot(repo), TODAY)[0]
    assert o.days_to_expiry == 79 and o.competitor_streak == 3
    assert o.components["expiry"] == 82 and o.components["pattern"] == 100
    assert o.expected_rebid == date(2026, 12, 26).replace(month=11, day=11)    # D-45
    assert 0 <= o.score <= 100 and any("D-79" in r for r in o.reasons)
    assert any("약제부" in a.text for a in recommend_actions(o))


def test_demo_scores_sorted_and_bounded(demo_repo):
    opps = compute_opportunities(load_snapshot(demo_repo), TODAY)
    assert opps and all(0 <= o.score <= 100 for o in opps)
    assert [o.score for o in opps] == sorted((o.score for o in opps), reverse=True)


def test_actions_by_urgency(demo_repo):
    o = compute_opportunities(load_snapshot(demo_repo), TODAY)[0]
    o.days_to_expiry, o.open_bid_count, o.competitor_streak = 5, 0, 0
    acts = recommend_actions(o)
    assert acts[0].urgency == "긴급" and "즉시" in acts[0].text
    o.days_to_expiry = None
    assert recommend_actions(o)[0].text.startswith("정기 방문")


def test_alerts_dedup_and_milestones(demo_repo):
    first = generate_alerts(demo_repo, TODAY)
    kinds = {a["alert_type"] for a in first}
    assert {"NEW_BID", "CONTRACT_EXPIRY", "AWARD"} <= kinds <= {"NEW_BID", "DEADLINE", "AWARD", "FAILED", "REBID", "CONTRACT_EXPIRY"}
    assert generate_alerts(demo_repo, TODAY) == []                       # 재실행해도 중복 없음
    assert len(demo_repo.rows("alerts")) == len(first)
    assert all(a["dedup_key"].startswith(("NEW_BID:", "EXP:", "AWD:", "DL:", "FL:", "RB:")) for a in first)
    assert all(isinstance(a["payload"], dict) and a["payload"].get("title") for a in first)


def test_competitor_award_alert_skips_users_of_the_winning_company(repo):
    """자사 수주 알림 제외는 '받는 사람의 회사' 기준이다 (코드에 특정 회사를 박아 두지 않는다)."""
    hid = _add(repo)
    repo.upsert("awards", [{"award_key": "own", "bid_ntce_no": "own", "hospital_id": hid, "inst_name": "테스트병원", "result_status": "낙찰",
                            "winner_name": "가나제약(주)", "title": "의약품 구매", "award_amount": 1e8, "award_date": TODAY.isoformat(), "is_pharma": True}])
    fresh = generate_alerts(repo, TODAY)
    assert [a["alert_type"] for a in fresh] == ["AWARD"]                       # 알림 자체는 만들어진다
    alert = fresh[0]
    users = [{"id": 1, "is_active": True, "company_id": 10}, {"id": 2, "is_active": True, "company_id": 20}]
    subs = [{"user_id": 1, "hospital_id": None, "alert_types": None}, {"user_id": 2, "hospital_id": None, "alert_types": None}]
    got = recipients_for(alert, users, subs, {10: ["가나제약"], 20: ["다라바이오"]})
    assert [u["id"] for u in got] == [2]                                       # 낙찰받은 회사(10) 사용자는 제외
    assert [u["id"] for u in recipients_for(alert, users, subs)] == [1, 2]     # 회사 정보가 없으면 거르지 않는다


def test_recipients_respect_subscription_scope_and_types():
    users = [{"id": 1, "is_active": True}, {"id": 2, "is_active": True}, {"id": 3, "is_active": False}]
    subs = [{"user_id": 1, "hospital_id": 10, "alert_types": ["NEW_BID"]},
            {"user_id": 2, "hospital_id": None, "alert_types": None},
            {"user_id": 3, "hospital_id": None}]
    got = lambda a: sorted(u["id"] for u in recipients_for(a, users, subs))
    assert got({"alert_type": "NEW_BID", "hospital_id": 10}) == [1, 2]
    assert got({"alert_type": "NEW_BID", "hospital_id": 11}) == [2]
    assert got({"alert_type": "CONTRACT_EXPIRY", "hospital_id": 10}) == [2]


# ── 대시보드(공고 중심) ─────────────────────────────────────────
def _bid(no, title, bid_date, deadline, budget=1e8, pharma=True, tags=("의약품(일반)",), hosp="A병원"):
    import pandas as pd

    return {"bid_ntce_no": no, "title": title, "bid_date": pd.Timestamp(bid_date), "deadline": pd.Timestamp(deadline) if deadline else pd.NaT,
            "budget": budget, "is_pharma": pharma, "product_tags": list(tags), "hospital": hosp, "url": None}


def test_bid_overview_counts_lists_and_charts():
    import pandas as pd
    from datetime import date

    from hbr.analytics.metrics import bid_overview

    today = date(2026, 10, 8)
    df = pd.DataFrame([
        _bid("1", "신규+마감임박", "2026-10-07", "2026-10-10 12:00", budget=2e8, tags=("백신",)),
        _bid("2", "신규", "2026-10-06", "2026-10-30", hosp="B병원"),
        _bid("3", "오래된 공고(진행중)", "2026-09-01", "2026-10-20", hosp="B병원"),
        _bid("4", "이미 마감", "2026-09-01", "2026-10-01"),
        _bid("5", "의약품 아님", "2026-10-07", "2026-10-12", pharma=False, tags=()),
    ])
    o = bid_overview(df, today, pharma=True)
    assert o["kpi"] == {"new": 2, "open": 3, "closing": 1, "budget": 4e8, "open_all": 4}
    assert list(o["new"]["bid_ntce_no"]) == ["1", "2"]                  # 최신 등록순
    assert list(o["closing"]["bid_ntce_no"]) == ["1"]
    assert len(o["trend"]) == 30 and int(o["trend"]["건수"].sum()) == 2      # 30일 이전(9/1) 공고는 추이에서 제외
    assert dict(zip(o["tags"]["분류"], o["tags"]["건수"])) == {"백신": 1, "의약품(일반)": 2}
    assert dict(zip(o["hospitals"]["기관"], o["hospitals"]["건수"])) == {"A병원": 1, "B병원": 2}
    allv = bid_overview(df, today, pharma=False)
    assert allv["kpi"]["open"] == 4 and allv["kpi"]["new"] == 3


def test_bid_overview_handles_empty_and_missing_deadline():
    import pandas as pd
    from datetime import date

    from hbr.analytics.metrics import bid_overview

    today = date(2026, 10, 8)
    e = bid_overview(pd.DataFrame(), today)
    assert e["empty"] and e["kpi"]["open"] == 0 and len(e["trend"]) == 30
    df = pd.DataFrame([_bid("1", "마감 미정", "2026-10-07", None)])
    o = bid_overview(df, today)
    assert o["kpi"]["open"] == 1 and o["kpi"]["closing"] == 0          # 마감일이 없으면 진행중이지만 임박으로는 세지 않는다
