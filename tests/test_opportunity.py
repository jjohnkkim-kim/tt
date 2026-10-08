from datetime import date

import pandas as pd

from hbr.analytics.data import Snapshot
from hbr.analytics.opportunity import (company_opportunities, competition_score, fit_score, forecast, market_scores,
                                       repeat_score, timing_score)

T = pd.Timestamp
TODAY = date(2026, 10, 8)


def test_component_functions():
    assert fit_score(2, 0) == 100 and fit_score(1, 3) == 80 and fit_score(0, 2) == 50 and fit_score(0, 0) == 0
    assert timing_score(None) == 0 and timing_score(2) == 100 and timing_score(20) == 40
    assert competition_score(0.0, 5) == 100 and competition_score(1.0, 1) < 10
    assert repeat_score(None) is None and repeat_score(10) == 100 and repeat_score(-30) == 20
    s = market_scores({1: 1e9, 2: 1e6})
    assert s[1] == 100 and 0 < s[2] < 100


def bid(no, title, d, hosp=1, deadline=None, budget=1e8, pharma=True):
    return {"bid_ntce_no": no, "bid_ntce_ord": "000", "title": title, "bid_date": T(d), "hospital_id": hosp, "is_pharma": pharma,
            "deadline": T(deadline) if deadline else pd.NaT, "budget": budget}


def snap(bids, awards=()):
    hosp = pd.DataFrame({"id": [1, 2], "name": ["가병원", "나병원"]})
    return Snapshot(hosp, pd.DataFrame(), pd.DataFrame(bids), pd.DataFrame(list(awards)), pd.DataFrame(), pd.DataFrame())


def mt(level):
    return {"match_level": level}


def test_no_matches_means_no_scores():
    s = snap([bid("a", "x", "2026-10-01")])
    assert company_opportunities(s, pd.DataFrame(), TODAY).empty


def test_fit_and_missing_data_are_reported_not_zeroed():
    s = snap([bid("a", "알부민 주", "2026-10-05", hosp=1, deadline="2026-10-12"), bid("b", "다른 주", "2026-10-05", hosp=2, deadline="2026-10-12")])
    m = pd.DataFrame([mt("HIGH"), mt(None)], index=s.bids.index)
    df = company_opportunities(s, m, TODAY).set_index("병원")
    assert df.loc["가병원", "맞는공고"] == 1 and df.loc["나병원", "맞는공고"] == 0
    assert df.loc["가병원", "점수"] > df.loc["나병원", "점수"]
    assert set(df.loc["가병원", "missing"]) == {"competition", "repeat"}          # 낙찰 5건 미만·반복 품목 없음 → 점수에서 빠짐
    assert "competition" not in df.loc["가병원", "components"]


def test_competition_needs_five_awards_and_own_wins_lower_it():
    awards = [{"hospital_id": 1, "award_date": T("2026-09-%02d" % (i + 1)), "winner_name": f"업체{i % 3}", "winner_biz_no": None,
               "bid_ntce_no": f"n{i}", "award_amount": 1e6, "is_own": i < 3, "is_pharma": True, "result_status": "낙찰"} for i in range(6)]
    s = snap([bid("a", "알부민 주", "2026-10-05", deadline="2026-10-12")], awards)
    m = pd.DataFrame([mt("HIGH")], index=s.bids.index)
    r = company_opportunities(s, m, TODAY).set_index("병원").loc["가병원"]
    assert "competition" in r["components"] and r["components"]["competition"] < 70       # 자사 낙찰 절반 → 여지 낮음


def test_forecast_ignores_rebid_chains_and_far_future():
    b = pd.DataFrame([bid(f"n{i}", "독감백신 공급", d) for i, d in enumerate(["2026-08-01", "2026-08-31", "2026-09-30"])]
                     + [bid(f"r{i}", "(재공고)백신 B", d) for i, d in enumerate(["2026-09-01", "2026-09-05", "2026-09-09"])])
    f = forecast(b, TODAY, lambda h: f"병원{h}")
    assert list(f["품목"]) == ["독감백신 공급"] and f.iloc[0]["병원"] == "병원1"
    assert f.iloc[0]["다음 입찰 예상(추정)"] == T("2026-10-30") and f.iloc[0]["D-day"] == 22
    assert forecast(b, TODAY, horizon_days=10).empty
