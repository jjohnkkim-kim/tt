import json

import pytest

from hbr.collectors.g2b import G2BClient, G2BError


def ok(items, total=None):
    return json.dumps({"response": {"header": {"resultCode": "00", "resultMsg": "OK"},
                                    "body": {"items": items, "totalCount": total if total is not None else len(items)}}})


def test_parse_list_and_single_item():
    assert G2BClient.parse_response(ok([{"a": 1}, {"a": 2}]))["total"] == 2
    single = json.dumps({"response": {"header": {"resultCode": "00"}, "body": {"items": {"item": {"a": 1}}, "totalCount": 1}}})
    assert G2BClient.parse_response(single)["items"] == [{"a": 1}]


def test_parse_empty():
    r = G2BClient.parse_response(ok([]))
    assert r == {"items": [], "total": 0}


def test_api_error_json_and_xml():
    bad = json.dumps({"response": {"header": {"resultCode": "30", "resultMsg": "SERVICE KEY ERROR"}, "body": {}}})
    with pytest.raises(G2BError, match="30"):
        G2BClient.parse_response(bad)
    xml = "<OpenAPI_ServiceResponse><cmmMsgHeader><returnReasonCode>30</returnReasonCode><returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</returnAuthMsg></cmmMsgHeader></OpenAPI_ServiceResponse>"
    with pytest.raises(G2BError, match="SERVICE_KEY"):
        G2BClient.parse_response(xml)


def test_gateway_error_json():
    body = json.dumps({"OpenAPI_ServiceResponse": {"cmmMsgHeader": {
        "errMsg": "SERVICE_KEY_IS_NOT_REGISTERED_ERROR", "returnAuthMsg": "등록되지 않은 서비스키",
        "returnReasonCode": "30"}}})
    with pytest.raises(G2BError, match="30.*등록되지 않은 서비스키"):
        G2BClient.parse_response(body, 403)


def test_missing_key():
    with pytest.raises(G2BError):
        G2BClient("", "http://x")
    with pytest.raises(G2BError):
        G2BClient("YOUR_SERVICE_KEY", "http://x")


class FakeSession:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def get(self, url, params, timeout):
        self.calls.append((url, params))

        class R:
            status_code = 200
            text = self.pages[(len(self.calls) - 1) % len(self.pages)]
        return R()


def test_fetch_paginates_and_splits_windows():
    from datetime import date

    sess = FakeSession([ok([{"n": 1}, {"n": 2}], total=3), ok([{"n": 3}], total=3)])
    c = G2BClient("abc%2Bdef", "http://api/x", rows_per_page=2, session=sess)
    assert c.service_key == "abc+def"          # Encoding 키 입력 시 이중 인코딩 방지
    out = list(c.fetch("bids", date(2026, 10, 1), date(2026, 10, 3)))
    assert [o["n"] for o in out] == [1, 2, 3]
    url, params = sess.calls[0]
    assert url.endswith("getDataSetOpnStdBidPblancInfo")
    assert params["bidNtceBgnDt"] == "202610010000" and params["bidNtceEndDt"] == "202610032359"
    assert [c[1]["pageNo"] for c in sess.calls] == [1, 2]


def test_contract_dates_are_yyyymmdd():
    from datetime import date

    sess = FakeSession([ok([])])
    list(G2BClient("k", "http://api/x", session=sess).fetch("contracts", date(2026, 10, 1), date(2026, 10, 2)))
    assert sess.calls[0][1]["cntrctCnclsBgnDate"] == "20261001"


def test_param_error_envelope_raises():
    body = json.dumps({"nkoneps.com.response.ResponseError": {"header": {"resultCode": "08", "resultMsg": "필수값 입력 에러"}}})
    with pytest.raises(G2BError, match="08.*필수값"):
        G2BClient.parse_response(body)


def test_awards_fetch_one_day_windows_per_business_division():
    from datetime import date

    sess = FakeSession([ok([])])
    list(G2BClient("k", "http://api/x", session=sess).fetch("awards", date(2026, 10, 1), date(2026, 10, 2)))
    got = [(p["opengBgnDt"], p["bsnsDivCd"]) for _, p in sess.calls]
    assert got == [("202610010000", c) for c in "12"] + [("202610020000", c) for c in "12"]      # 기본: 물품·외자만
    assert all(p["opengEndDt"] == p["opengBgnDt"][:8] + "2359" for _, p in sess.calls)


def test_error_message_redacts_service_key():
    import requests

    class Boom:
        def get(self, url, params=None, timeout=None):
            from urllib.parse import urlencode

            raise requests.ConnectionError(f"Max retries exceeded with url: /op?{urlencode(params)}")

    key = "ab+cd/ef=="
    c = G2BClient(key, "http://api/x", max_retries=1, session=Boom())
    with pytest.raises(G2BError) as e:
        c._request("op", {})
    msg = str(e.value)
    assert "serviceKey=***" in msg and "ab%2Bcd" not in msg and "ab+cd" not in msg


def test_award_divisions_configurable_and_sanitized(monkeypatch):
    from hbr.collectors.g2b import award_divisions

    assert award_divisions() == ["1", "2"]
    monkeypatch.setenv("AWARD_DIVISIONS", "1, 5")
    assert award_divisions() == ["1", "5"]
    monkeypatch.setenv("AWARD_DIVISIONS", "9,x")
    assert award_divisions() == ["1", "2"]                      # 잘못된 값이면 안전한 기본값
