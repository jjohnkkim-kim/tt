from datetime import date

import pandas as pd
import pytest

from hbr.notify.telegram import TelegramError, build_digest, find_chat_ids, send_message, split_message

TODAY = date(2026, 10, 8)


def bids(rows):
    base = {"bid_ntce_no": "N0", "title": "t", "hospital": "H병원", "bid_date": pd.Timestamp("2026-10-08"),
            "deadline": pd.Timestamp("2026-10-20"), "budget": 162_000_000.0, "is_pharma": True,
            "product_tags": ["백신"], "url": "https://www.g2b.go.kr/x?a=1&b=2"}
    return pd.DataFrame([{**base, **r} for r in rows])


def test_digest_new_and_deadline_sections_with_links():
    df = bids([{"bid_ntce_no": "N1", "title": "신규 <의약품>"},
               {"bid_ntce_no": "N2", "title": "마감임박", "bid_date": pd.Timestamp("2026-09-30"),
                "deadline": pd.Timestamp("2026-10-10 12:00")},
               {"bid_ntce_no": "N3", "title": "의약품 아님", "is_pharma": False}])
    text = build_digest(df, TODAY)
    assert "신규 의약품 공고 1건" in text and "마감 임박(3일 이내) 1건" in text
    assert "&lt;의약품&gt;" in text                      # HTML 이스케이프
    assert 'href="https://www.g2b.go.kr/x?a=1&amp;b=2"' in text
    assert "1.62억" in text and "D-2" in text and "〔백신〕" in text
    assert "의약품 아님" not in text


def test_amount_format_small_and_zero():
    from hbr.notify.telegram import _won

    assert _won(41_000_000) == " · 4,100만원" and _won(0) == "" and _won(None) == "" and _won(1_100_000_000) == " · 11.00억"


def test_digest_dedupes_new_that_is_also_closing_soon_and_empty_returns_none():
    df = bids([{"bid_ntce_no": "N1", "deadline": pd.Timestamp("2026-10-09")}])
    text = build_digest(df, TODAY)
    assert "신규" not in text and "마감 임박(3일 이내) 1건" in text
    assert build_digest(bids([{"is_pharma": False}]), TODAY) is None
    assert build_digest(pd.DataFrame(), TODAY) is None


def test_digest_caps_items():
    df = bids([{"bid_ntce_no": f"N{i}", "title": f"공고{i}"} for i in range(20)])
    assert "… 외 5건" in build_digest(df, TODAY)


def test_split_message_respects_limit():
    text = "\n".join("x" * 100 for _ in range(100))
    chunks = split_message(text, 1000)
    assert len(chunks) > 1 and all(len(c) <= 1000 for c in chunks) and "\n".join(chunks) == text


class FakeResp:
    def __init__(self, status=200, body=None):
        self.status_code, self._b, self.content, self.text = status, body or {}, b"x", "x"

    def json(self):
        return self._b


class FakeSession:
    def __init__(self, resp):
        self.resp, self.calls = resp, []

    def post(self, url, **kw):
        self.calls.append((url, kw))
        return self.resp

    def get(self, url, **kw):
        self.calls.append((url, kw))
        return self.resp


def test_send_message_ok_and_payload():
    s = FakeSession(FakeResp(200, {"ok": True}))
    assert send_message("TOK", "123", "hello", session=s) == 1
    url, kw = s.calls[0]
    assert url.endswith("/botTOK/sendMessage") and kw["json"]["chat_id"] == "123" and kw["json"]["parse_mode"] == "HTML"


def test_send_message_error_hides_token_and_missing_config():
    s = FakeSession(FakeResp(401, {"ok": False, "description": "Unauthorized"}))
    with pytest.raises(TelegramError, match="Unauthorized") as e:
        send_message("SECRETTOK", "1", "x", session=s)
    assert "SECRETTOK" not in str(e.value)
    with pytest.raises(TelegramError):
        send_message("", "", "x")


def test_find_chat_ids():
    s = FakeSession(FakeResp(200, {"ok": True, "result": [
        {"message": {"chat": {"id": 42, "first_name": "나"}}}, {"message": {"chat": {"id": 42, "first_name": "나"}}}]}))
    assert find_chat_ids("TOK", session=s) == [("42", "나")]
