from datetime import date

from hbr.etl.normalize import normalize_award, normalize_bid, normalize_contract
from hbr.etl.pipeline import dedupe, run_dataset

BID = {"bidNtceNo": "20261000001", "bidNtceOrd": "00", "bidNtceNm": "알부민 20% 구매", "dminsttNm": "서울대학교병원",
       "ntceInsttNm": "조달청", "bidNtceDt": "2026-10-08 09:00:00", "bidClseDt": "2026-10-23 10:00:00",
       "asignBdgtAmt": "500,000,000", "bidMethdNm": "전자입찰"}


def test_normalize_bid():
    b = normalize_bid(BID)
    assert b["bid_key"] == "20261000001-00" and b["is_pharma"] and "알부민" in b["product_tags"]
    assert b["budget"] == 5e8 and b["bid_date"] == date(2026, 10, 8)
    assert b["deadline"].startswith("2026-10-23T10:00") and b["deadline"].endswith("+09:00")


def test_non_hospital_dropped():
    assert normalize_bid({**BID, "dminsttNm": "서울특별시", "ntceInsttNm": "서울특별시"}) is None
    assert normalize_bid({**BID, "bidNtceNo": ""}) is None


def test_hospital_picked_from_notice_agency_when_demand_agency_is_not_one():
    b = normalize_bid({**BID, "dminsttNm": "조달청", "ntceInsttNm": "삼성서울병원"})
    assert b["inst_name"] == "삼성서울병원"


def test_normalize_award_matches_competitor(repo):
    comps = repo.competitor_index()
    a = normalize_award({"bidNtceNo": "1", "bidNtceNm": "면역글로불린", "dminsttNm": "삼성서울병원", "bidwinnrNm": "GC녹십자",
                         "bidwinnrBizno": "123-45-67890", "sucsfbidAmt": "300000000", "opengDt": "2026-10-01"}, comps)
    assert a["winner_biz_no"] == "123-45-67890"
    assert a["competitor_id"] is not None and a["award_amount"] == 3e8 and a["award_date"] == date(2026, 10, 1)


def test_contract_end_from_period_text_and_estimate(repo):
    comps = repo.competitor_index()
    base = {"untyCntrctNo": "C1", "cntrctNm": "의약품 구매", "dminsttNm": "서울대학교병원", "cntrctCorpNm": "JW중외제약",
            "totCntrctAmt": "1000000000", "cntrctCnclsDate": "2026-01-15"}
    c = normalize_contract({**base, "cntrctPrdCn": "2026.02.01 ~ 2027.01.31"}, comps)
    assert c["start_date"] == date(2026, 2, 1) and c["end_date"] == date(2027, 1, 31) and not c["end_date_estimated"]
    c2 = normalize_contract(base, comps)
    assert c2["end_date"] == date(2027, 1, 15) and c2["end_date_estimated"]


def test_dedupe_keeps_more_complete_row():
    rows = [{"k": "a", "x": None, "y": 1}, {"k": "a", "x": 5, "y": 1}, {"k": "b", "x": 1}]
    out = {r["k"]: r for r in dedupe(rows, "k")}
    assert out["a"]["x"] == 5 and len(out) == 2


class FakeClient:
    def __init__(self, data):
        self.data = data

    def fetch(self, dataset, start, end):
        yield from self.data.get(dataset, [])


def test_pipeline_filters_dedupes_and_is_idempotent(repo):
    other = {**BID, "bidNtceNo": "999", "dminsttNm": "서울특별시청", "ntceInsttNm": "서울특별시청"}
    client = FakeClient({"bids": [BID, BID, other]})
    st = run_dataset(repo, client, "bids", date(2026, 10, 1), date(2026, 10, 8))
    assert (st.fetched, st.kept, st.upserted) == (3, 2, 1) and st.ok
    run_dataset(repo, client, "bids", date(2026, 10, 1), date(2026, 10, 8))
    assert len(repo.rows("bids")) == 1 and len(repo.rows("hospitals")) == 1
    assert repo.rows("pipeline_runs")[0]["status"] == "success"


def test_pipeline_failure_is_logged_not_raised(repo):
    class Boom:
        def fetch(self, *a):
            raise RuntimeError("api down")
            yield

    st = run_dataset(repo, Boom(), "bids", date(2026, 10, 1), date(2026, 10, 2))
    assert not st.ok and "api down" in st.error
    assert repo.rows("pipeline_runs")[0]["status"] == "failed"
