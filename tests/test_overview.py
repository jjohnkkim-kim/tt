from datetime import date

import pandas as pd

from hbr.analytics.data import Snapshot
from hbr.analytics.lifecycle import build_lifecycle
from hbr.analytics.matching import match_frame
from hbr.analytics.overview import build_overview, closing_bucket

TODAY = date(2026, 10, 8)
T = pd.Timestamp
PRODUCTS = [{"id": 1, "name": "알파주", "product_group": "항체"}]


def bid(no, title, bid_date, deadline, pharma=True, **kw):
    return {"bid_ntce_no": no, "bid_ntce_ord": "000", "title": title, "hospital_id": 1, "hospital": "A병원", "bid_date": T(bid_date),
            "deadline": T(deadline) if deadline else pd.NaT, "open_date": pd.NaT, "budget": 1e8, "is_pharma": pharma, "product_tags": [], **kw}


def res(no, status, d, own=False, **kw):
    return {"bid_ntce_no": no, "bid_ntce_ord": "000", "title": "의약품", "hospital_id": 1, "hospital": "A병원", "award_date": T(d), "is_pharma": True,
            "result_status": status, "winner_name": "제약" if status == "낙찰" else None, "is_own": own, **kw}


def snap():
    bids = pd.DataFrame([
        bid("1", "알파주 구매", "2026-10-08", "2026-10-09 10:00"),                  # 오늘 신규 + 관심제품 + 마감 D-1
        bid("2", "(재공고)일반 의약품 단가", "2026-10-07", "2026-10-14"),              # 신규 + 재공고 + 마감 D-6
        bid("3", "의약품 단가", "2026-09-20", "2026-10-30"),                          # 오래됨(신규 아님), 진행중
        bid("4", "알파주 연구 용역", "2026-10-07", "2026-10-20", pharma=False),         # 의약품 아님
        bid("5", "항체 의약품 구매", "2026-10-06", "2026-10-25"),                     # 제품군만 → 검토 필요(LOW)
    ])
    return Snapshot(pd.DataFrame(), pd.DataFrame(), bids,
                    pd.DataFrame([res("A1", "낙찰", "2026-10-05"), res("A1", "낙찰", "2026-10-05"), res("A2", "낙찰", "2026-10-06", own=True),
                                  res("A3", "낙찰", "2026-08-01")]),
                    pd.DataFrame([{"hospital_id": 1, "hospital": "A병원", "title": "계약", "vendor_name": "제약", "contract_amount": 1e7,
                                   "contract_date": T("2026-10-01"), "end_date": pd.NaT, "is_pharma": True, "raw": {}}]),
                    pd.DataFrame([res("F1", "유찰", "2026-10-07")]))


def overview(start, end, products=PRODUCTS, pharma=True):
    s = snap()
    return build_overview(s, build_lifecycle(s, TODAY), match_frame(s.bids, products), TODAY, start, end, pharma, has_products=bool(products))


def test_period_filters_new_related_and_rebid():
    o = overview(TODAY, TODAY)                                      # 오늘
    assert o["kpi"]["new"] == 1 and o["kpi"]["related"] == 1 and o["kpi"]["rebid"] == 0
    o7 = overview(date(2026, 10, 2), TODAY)                         # 최근 7일
    assert o7["kpi"]["new"] == 3 and o7["kpi"]["rebid"] == 1        # 의약품 아닌 공고(4번)는 제외, 재공고(2번) 포함
    assert o7["kpi"]["related"] == 1 and o7["kpi"]["review"] == 1  # 알파주 HIGH 1건 + 제품군만 일치 LOW 1건(검토 필요)
    assert list(o7["related"]["bid_ntce_no"]) == ["1"]


def test_pharma_toggle_adds_non_pharma_bids():
    assert overview(date(2026, 10, 2), TODAY, pharma=False)["kpi"]["new"] == 4


def test_closing_is_independent_of_period_and_bucketed():
    o = overview(TODAY, TODAY)
    assert list(o["closing"]["bid_ntce_no"]) == ["1", "2"]          # 7일 이내 마감, 빠른 순 (3·5번은 7일 넘게 남음)
    assert list(closing_bucket(o["closing"], TODAY, 1)["bid_ntce_no"]) == ["1"]
    assert list(closing_bucket(o["closing"], TODAY, 7)["bid_ntce_no"]) == ["1", "2"]


def test_results_counted_per_bid_in_period_and_competitor_excludes_own():
    o = overview(date(2026, 10, 2), TODAY)
    assert o["kpi"]["awarded"] == 2 and o["kpi"]["failed"] == 1     # 같은 공고(A1) 중복 행은 한 건, 8월 낙찰은 기간 밖
    assert o["kpi"]["competitor_awards"] == 1                       # 자사(A2) 제외
    assert overview(TODAY, TODAY)["kpi"]["awarded"] == 0            # 낙찰은 며칠 뒤 공개되어 오늘은 비어 있을 수 있다


def test_contracts_without_end_date_are_not_counted_as_expiring():
    o = overview(date(2026, 10, 2), TODAY)
    assert o["kpi"]["expiring"] == 0 and o["contracts_total"] == 1 and o["contracts_with_end"] == 0


def test_no_products_means_no_matches_and_empty_inputs_are_safe():
    o = overview(date(2026, 10, 2), TODAY, products=[])
    assert o["kpi"]["related"] == 0 and o["kpi"]["review"] == 0 and not o["has_products"]
    empty = build_overview(Snapshot(*[pd.DataFrame()] * 5), pd.DataFrame(), pd.DataFrame(), TODAY, TODAY, TODAY)
    assert set(empty["kpi"].values()) == {0}
