import json

import pytest

from hbr.collectors.field_check import analyze, collect_sample, render
from hbr.collectors.g2b import G2BError
from hbr.constants import COMPETITOR_SEEDS
from scripts.check_g2b_fields import main

COMPS = [{"id": i + 1, "name": n, "aliases": a, "is_own": o} for i, (n, a, o) in enumerate(COMPETITOR_SEEDS)]

GOOD_BID = {"bidNtceNo": "20261000001", "bidNtceOrd": "00", "bidNtceNm": "알부민 구매", "dminsttNm": "서울대학교병원",
            "bidNtceDt": "2026-10-08 09:00:00", "bidClseDt": "2026-10-23 10:00:00", "asignBdgtAmt": "500000000",
            "bidMethdNm": "전자입찰"}
OTHER_BID = {**GOOD_BID, "bidNtceNo": "2", "dminsttNm": "서울특별시청"}


class FakeClient:
    def __init__(self, data, error=None):
        self.data, self.error = data, error
        self.fetched = 0

    def probe(self, dataset, start, end):
        if self.error:
            raise self.error
        return {"operation": f"op_{dataset}", "params": {"pageNo": 1}, "total": len(self.data.get(dataset, [])),
                "items": self.data.get(dataset, [])[:1]}

    def fetch(self, dataset, start, end):
        for r in self.data.get(dataset, []):
            self.fetched += 1
            yield r


def test_good_response_maps_all_fields():
    rep = analyze("bids", [GOOD_BID, OTHER_BID], [GOOD_BID], COMPS)
    by = {s.logical: s for s in rep.stats}
    assert by["deadline"].matched == "bidClseDt" and by["deadline"].parsed == 1.0
    assert by["budget"].matched == "asignBdgtAmt" and by["budget"].parsed == 1.0
    assert rep.ok and not rep.missing_required and rep.normalized == 1 and rep.hospital_rows == 1
    assert rep.missing_important == []                          # 선택 필드(url 등)가 없어도 정상


def test_renamed_fields_are_flagged_with_hints():
    renamed = {"bidNtceNo": "1", "bidNtceNm": "알부민", "dminsttNm": "서울대학교병원", "bidNtceDt": "2026-10-08",
               "bidClseDtm": "2026-10-23 10:00:00", "bdgtAmount": "500000000"}
    rep = analyze("bids", [renamed], [renamed], COMPS)
    assert "deadline" in rep.missing_important and "budget" in rep.missing_important and rep.ok   # 필수는 통과
    by = {s.logical: s for s in rep.stats}
    assert "bidClseDtm" in by["deadline"].hints and "bdgtAmount" in by["budget"].hints
    text = render(rep)
    assert "후보 추정: bidClseDtm" in text and "FIELDS['bids']['deadline']" in text


def test_missing_required_makes_report_fail():
    bad = {"title": "x", "instNm": "서울대학교병원"}            # 공고번호·기관 필드 모두 낯선 이름
    rep = analyze("bids", [bad], [], COMPS)
    assert not rep.ok and {"inst", "no"} <= set(rep.missing_required)
    assert "필수 필드 미매칭" in render(rep)


def test_unparseable_dates_reported():
    rows = [{**GOOD_BID, "bidClseDt": "내일 오전"} for _ in range(3)]
    rep = analyze("bids", rows, rows, COMPS)
    assert {s.logical: s for s in rep.stats}["deadline"].parsed == 0.0
    assert any(l.strip().startswith("△ deadline") and " 0%" in l for l in render(rep).splitlines())


def test_empty_response():
    rep = analyze("bids", [], [], COMPS)
    assert not rep.ok and "비어 있습니다" in render(rep)


def test_collect_sample_stops_early():
    rows = [OTHER_BID] * 50 + [GOOD_BID] * 30
    c = FakeClient({"bids": rows})
    sample, hosp, scanned = collect_sample(c, "bids", None, None, max_rows=10, scan_limit=1000, want_hospital=5)
    assert len(sample) == 10 and len(hosp) == 5 and scanned == 55 and c.fetched == 55      # 병원 5건 채우면 즉시 중단
    c2 = FakeClient({"bids": [OTHER_BID] * 100})
    assert collect_sample(c2, "bids", None, None, 10, scan_limit=40)[2] == 40                # scan_limit 준수


def test_cli_ok_and_sample_saved_without_key(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("SERVICE_KEY", "TOP-SECRET-KEY")
    out = tmp_path / "s" / "sample.json"
    client = FakeClient({"bids": [GOOD_BID, OTHER_BID]})
    code = main(["--dataset", "bids", "--save-sample", str(out)], client=client)
    printed = capsys.readouterr().out
    assert code == 0 and "TOP-SECRET-KEY" not in printed and "TOP-SECRET-KEY" not in out.read_text(encoding="utf-8")
    assert json.loads(out.read_text(encoding="utf-8"))["bids"][0]["bidNtceNo"] == "20261000001"
    assert "getDataSetOpnStdBidPblancInfo" in printed and "모든 데이터셋 정상" in printed


def test_cli_api_error_and_missing_key(capsys, monkeypatch):
    assert main(["--dataset", "awards"], client=FakeClient({}, error=G2BError("API 오류 30: SERVICE_KEY_IS_NOT_REGISTERED"))) == 1
    assert "호출 실패" in capsys.readouterr().out
    monkeypatch.setenv("SERVICE_KEY", "")
    monkeypatch.setattr("scripts.check_g2b_fields.get_settings", lambda: __import__("hbr.config", fromlist=["x"]).get_settings())
    assert main(["--dataset", "bids"]) == 2


def test_probe_builds_request_without_key():
    from datetime import date

    from hbr.collectors.g2b import G2BClient

    class Sess:
        def get(self, url, params, timeout):
            self.params = params

            class R:
                status_code = 200
                text = json.dumps({"response": {"header": {"resultCode": "00"}, "body": {"items": [{"a": 1}], "totalCount": 7}}})
            return R()
    sess = Sess()
    res = G2BClient("KEY123", "http://api", session=sess).probe("bids", date(2026, 10, 7), date(2026, 10, 8))
    assert res["total"] == 7 and res["operation"] == "getDataSetOpnStdBidPblancInfo"
    assert "serviceKey" not in res["params"] and sess.params["serviceKey"] == "KEY123"
    assert res["params"]["bidNtceBgnDt"] == "202610070000" and res["params"]["bidNtceEndDt"] == "202610072359"


@pytest.mark.parametrize("dataset", ["awards", "contracts"])
def test_other_datasets_analyze(dataset):
    row = ({"bidNtceNo": "1", "dminsttNm": "삼성서울병원", "bidwinnrNm": "GC녹십자", "sucsfbidAmt": "300000000", "opengDt": "2026-10-01"}
           if dataset == "awards" else
           {"untyCntrctNo": "C1", "dminsttNm": "삼성서울병원", "cntrctCorpNm": "JW중외제약", "totCntrctAmt": "1000000000",
            "cntrctCnclsDate": "2026-01-15", "cntrctEndDate": "2027-01-14"})
    rep = analyze(dataset, [row], [row], COMPS)
    assert rep.ok and rep.normalized == 1 and not rep.missing_important
