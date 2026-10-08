import math
from datetime import date, datetime
from decimal import Decimal

import pytest

from hbr.store.backends import MemoryBackend, clean_value


def test_clean_value():
    assert clean_value(date(2026, 1, 2)) == "2026-01-02"
    assert clean_value(datetime(2026, 1, 2, 3, 4)) == "2026-01-02T03:04:00"
    assert clean_value(Decimal("1.5")) == 1.5
    assert clean_value(math.nan) is None
    assert clean_value({"a": [date(2026, 1, 1)]}) == {"a": ["2026-01-01"]}


def test_memory_upsert_and_filters():
    b = MemoryBackend()
    b.upsert("bids", [{"bid_key": "a", "v": 1}, {"bid_key": "b", "v": 2}])
    b.upsert("bids", [{"bid_key": "a", "v": 9}])
    rows = b.select("bids", order="bid_key")
    assert [(r["bid_key"], r["v"], r["id"]) for r in rows] == [("a", 9, 1), ("b", 2, 2)]
    assert [r["bid_key"] for r in b.select("bids", [("v", "gte", 5)])] == ["a"]
    assert [r["bid_key"] for r in b.select("bids", [("bid_key", "in", ["b"])])] == ["b"]
    assert b.select("bids", order="-v", limit=1)[0]["bid_key"] == "a"
    b.update("bids", {"v": 0}, [("bid_key", "eq", "b")])
    b.delete("bids", [("bid_key", "eq", "a")])
    assert [(r["bid_key"], r["v"]) for r in b.select("bids")] == [("b", 0)]
    assert b.select("bids", [("nope", "isnull", True)])    # 없는 컬럼은 NULL 로 취급


def test_insert_duplicate_unique_raises():
    b = MemoryBackend()
    b.insert("users", [{"email": "a@x.com"}])
    with pytest.raises(ValueError):
        b.insert("users", [{"email": "a@x.com"}])


def test_select_returns_copies():
    b = MemoryBackend()
    b.insert("users", [{"email": "a@x.com", "role": "viewer"}])
    b.select("users")[0]["role"] = "admin"
    assert b.select("users")[0]["role"] == "viewer"


def test_watchlist(repo):
    u = repo.ensure_user("A@x.com", "A", "sales")
    assert repo.ensure_user("a@x.com", "A", "sales")["id"] == u["id"]
    assert repo.add_watch(u["id"], 5) and not repo.add_watch(u["id"], 5)
    assert repo.watched_hospital_ids(u["id"]) == {5}
    repo.remove_watch(u["id"], 5)
    assert repo.watched_hospital_ids(u["id"]) == set()
