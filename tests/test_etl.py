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


def test_contract_end_from_period_text_never_estimated(repo):
    comps = repo.competitor_index()
    base = {"untyCntrctNo": "C1", "cntrctNm": "의약품 구매", "dminsttNm": "서울대학교병원", "cntrctCorpNm": "JW중외제약",
            "totCntrctAmt": "1000000000", "cntrctCnclsDate": "2026-01-15"}
    c = normalize_contract({**base, "cntrctPrdCn": "2026.02.01 ~ 2027.01.31"}, comps)
    assert c["start_date"] == date(2026, 2, 1) and c["end_date"] == date(2027, 1, 31) and not c["end_date_estimated"]
    c2 = normalize_contract(base, comps)
    assert c2["end_date"] is None and not c2["end_date_estimated"]          # 종료일을 만들어 내지 않는다
    c3 = normalize_contract({**base, "cntrctPrd": "2027-12-31"}, comps)
    assert c3["end_date"] == date(2027, 12, 31)                              # 날짜 하나만 있으면 종료일
    assert normalize_contract({**base, "cntrctPrd": "1825"}, comps)["end_date"] is None   # 단위를 모르는 숫자는 쓰지 않는다


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


def test_real_api_field_names_award_and_contract():
    from hbr.etl.normalize import normalize_award, normalize_contract

    award = normalize_award({"bidNtceNo": "R26BK1", "bidNtceOrd": "000", "dmndInsttNm": "부산대학교병원", "bidNtceNm": "의약품 구매",
                             "fnlSucsfCorpNm": "(주)테스트제약", "fnlSucsfCorpBizrno": "1234567890", "fnlSucsfAmt": "1000000",
                             "fnlSucsfRt": "87.5", "fnlSucsfDate": "20261001"}, [])
    assert award and award["winner_name"] == "(주)테스트제약" and award["winner_biz_no"] == "1234567890"
    assert float(award["award_amount"]) == 1000000
    contract = normalize_contract({"untyCntrctNo": "C1", "cntrctNm": "공급", "dmndInsttNm": "제주대학교병원", "rprsntCorpNm": "테스트상사",
                                   "rprsntCorpBizrno": "9876543210", "ttalCntrctAmt": "5000", "cntrctAmt": "1000",
                                   "cntrctCnclsDate": "20261001"}, [])
    assert contract["vendor_name"] == "테스트상사" and contract["vendor_biz_no"] == "9876543210"
    assert float(contract["contract_amount"]) == 5000


def test_award_rows_become_awarded_or_failed_and_others_are_dropped():
    from hbr.etl.normalize import normalize_award

    base = {"bidNtceNo": "R26BK1", "bidNtceOrd": "000", "dmndInsttNm": "부산대학교병원", "bidNtceNm": "의약품 단가 계약", "bsnsDivNm": "물품",
            "opengDate": "2026-10-06"}
    won = normalize_award({**base, "opengRsltDivNm": "개찰완료", "fnlSucsfCorpNm": "(주)테스트제약", "fnlSucsfCorpBizrno": "1234567890",
                           "fnlSucsfAmt": "1000"}, [])
    assert won["result_status"] == "낙찰" and won["winner_name"] == "(주)테스트제약" and won["award_key"].endswith("-1234567890")
    lost = normalize_award({**base, "opengRsltDivNm": "유찰"}, [])
    assert lost["result_status"] == "유찰" and lost["winner_name"] is None and lost["award_amount"] is None
    assert lost["award_key"] == "R26BK1-000-유찰" and lost["award_date"] == date(2026, 10, 6)
    assert normalize_award({**base, "opengRsltDivNm": "개찰완료"}, []) is None      # 낙찰자 미정은 결과가 아니므로 저장하지 않는다


def test_awards_pipeline_stores_bidder_count_and_failed_rows(repo):
    base = {"bidNtceNo": "R1", "bidNtceOrd": "000", "dmndInsttNm": "부산대학교병원", "bidNtceNm": "의약품 단가 계약", "bsnsDivNm": "물품",
            "opengDate": "2026-10-06"}
    bidder = lambda n: {**base, "opengRsltDivNm": "개찰완료", "fnlSucsfCorpNm": "테스트제약", "fnlSucsfCorpBizrno": "1112223334", "opengRank": n}
    failed = {**base, "bidNtceNo": "R2", "opengRsltDivNm": "유찰"}
    pending = {**base, "bidNtceNo": "R3", "opengRsltDivNm": "개찰완료"}                        # 낙찰자 미정 → 저장 안 함
    st = run_dataset(repo, FakeClient({"awards": [bidder(1), bidder(2), bidder(3), failed, pending]}), "awards",
                     date(2026, 10, 1), date(2026, 10, 8))
    assert st.ok and st.fetched == 5 and st.kept == 4 and st.upserted == 2
    rows = {r["bid_ntce_no"]: r for r in repo.rows("awards")}
    assert rows["R1"]["result_status"] == "낙찰" and rows["R1"]["bidder_count"] == 3
    assert rows["R2"]["result_status"] == "유찰" and rows["R2"]["bidder_count"] == 1 and rows["R2"]["winner_name"] is None


def test_snapshot_keeps_failed_bids_out_of_award_analysis_and_counts_results(repo):
    from hbr.analytics.data import load_snapshot
    from hbr.analytics.metrics import result_counts
    from tests.conftest import TODAY

    hid = repo.upsert_hospitals([{"name": "부산대학교병원", "name_norm": "부산대학교병원", "hospital_type": "대학병원", "is_active": True}])["부산대학교병원"]
    common = {"hospital_id": hid, "inst_name": "부산대학교병원", "title": "의약품 단가", "is_pharma": True, "product_tags": [], "award_date": TODAY.isoformat()}
    repo.upsert("awards", [
        {**common, "award_key": "a", "bid_ntce_no": "A", "winner_name": "제약", "result_status": "낙찰", "award_amount": 100},
        {**common, "award_key": "b", "bid_ntce_no": "B", "winner_name": None, "result_status": "유찰"},
        {**common, "award_key": "b2", "bid_ntce_no": "B", "winner_name": None, "result_status": "유찰"}])      # 같은 공고 중복 행
    snap = load_snapshot(repo)
    assert list(snap.awards["bid_ntce_no"]) == ["A"] and list(snap.failed["bid_ntce_no"]) == ["B", "B"]
    assert result_counts(snap, TODAY, 30) == {"awarded": 1, "failed": 1}
