from datetime import date

import pandas as pd

from hbr.analytics.data import Snapshot
from hbr.analytics.patterns import hospital_pattern, repeated_items

T = pd.Timestamp
TODAY = date(2026, 10, 8)


def bid(title, d, hosp=1, pharma=True):
    return {"bid_ntce_no": f"{title}{d}", "bid_ntce_ord": "000", "title": title, "bid_date": T(d), "hospital_id": hosp, "is_pharma": pharma}


def snap(bids=(), awards=(), failed=(), contracts=()):
    f = lambda r: pd.DataFrame(list(r))
    return Snapshot(pd.DataFrame(), pd.DataFrame(), f(bids), f(awards), f(contracts), f(failed))


def test_repeated_items_need_three_occurrences_and_estimate_next_date():
    b = pd.DataFrame([bid("의약품 단가계약", "2026-06-01"), bid("의약품 단가계약", "2026-07-01"), bid("(재공고)의약품 단가계약", "2026-07-05"), bid("의약품 단가계약", "2026-07-31"),
                      bid("백신 구매", "2026-09-01"), bid("백신 구매", "2026-09-20")])                # 백신은 2회뿐
    rep = repeated_items(b)
    assert list(rep["품목"]) == ["의약품 단가계약"] and rep.iloc[0]["횟수"] == 3 and rep.iloc[0]["평균 간격(일)"] == 30.0
    assert rep.iloc[0]["다음 입찰 예상(추정)"] == T("2026-08-30")
    assert repeated_items(pd.DataFrame()).empty


def test_rebid_chain_is_not_a_purchase_cycle():
    b = pd.DataFrame([bid("독감백신 공급", "2026-09-01"), bid("(재공고)독감백신 공급", "2026-09-07"), bid("(재공고)독감백신 공급", "2026-09-13"),
                      bid("(재공고)독감백신 공급", "2026-09-19")])
    assert repeated_items(b).empty


def test_same_day_duplicates_do_not_make_a_cycle():
    b = pd.DataFrame([bid("의약품 단가", "2026-09-01"), bid("의약품 단가", "2026-09-01"), bid("의약품 단가", "2026-09-01")])
    assert repeated_items(b).empty


def test_counts_by_window_and_other_hospitals_and_non_pharma_are_excluded():
    s = snap([bid("a", "2026-10-01"), bid("b", "2026-09-01"), bid("c", "2026-03-01"), bid("d", "2026-10-02", hosp=2), bid("e", "2026-10-03", pharma=False)])
    p = hospital_pattern(s, 1, TODAY)
    assert p["counts"] == {"최근 1개월": 1, "최근 3개월": 2, "최근 1년": 3} and p["n_bids"] == 3       # 9/1 은 37일 전이라 1개월에 안 든다
    assert hospital_pattern(s, 1, TODAY, pharma=False)["counts"]["최근 1개월"] == 2                  # 의약품 아닌 공고(e)까지 포함


def test_rates_show_data_shortage_instead_of_numbers():
    p = hospital_pattern(snap([bid("(재공고)a", "2026-10-01"), bid("b", "2026-10-02")]), 1, TODAY)
    assert not p["rebid_rate"]["sufficient"] and p["rebid_rate"]["value"] is None and p["rebid_rate"]["n"] == 2
    assert not p["fail_rate"]["sufficient"] and not p["cycle_days"]["sufficient"] and not p["contract_months"]["sufficient"]
    many = hospital_pattern(snap([bid(("(재공고)" if i < 3 else "") + f"공고{i}", f"2026-09-{i + 1:02d}") for i in range(12)]), 1, TODAY)
    assert many["rebid_rate"]["sufficient"] and many["rebid_rate"]["value"] == 25.0


def test_fail_rate_counts_per_bid_and_needs_enough_results():
    res = lambda no, hosp=1: {"bid_ntce_no": no, "bid_ntce_ord": "000", "hospital_id": hosp, "title": "t", "award_date": T("2026-10-01"), "is_pharma": True}
    awarded = [res("A1"), res("A1"), res("A2"), res("A3")]                       # A1 은 투찰업체별 중복 행
    failed = [res("F1"), res("F2")]
    p = hospital_pattern(snap(awards=awarded, failed=failed), 1, TODAY)
    assert p["fail_rate"]["n"] == 5 and p["fail_rate"]["sufficient"] and p["fail_rate"]["value"] == 40.0


def test_contract_months_only_from_contracts_with_both_dates():
    con = lambda s, e: {"hospital_id": 1, "title": "c", "is_pharma": True, "start_date": T(s) if s else pd.NaT, "end_date": T(e) if e else pd.NaT}
    few = hospital_pattern(snap(contracts=[con("2026-01-01", "2026-12-31"), con("2026-02-01", None)]), 1, TODAY)
    assert not few["contract_months"]["sufficient"] and few["contract_months"]["n"] == 1
    enough = hospital_pattern(snap(contracts=[con("2026-01-01", "2026-12-31")] * 3), 1, TODAY)
    assert enough["contract_months"]["sufficient"] and 11.9 <= enough["contract_months"]["value"] <= 12.1


def test_empty_snapshot_is_safe():
    p = hospital_pattern(snap(), 1, TODAY)
    assert p["n_bids"] == 0 and p["counts"]["최근 1년"] == 0 and p["repeated"].empty and not p["cycle_days"]["sufficient"]
