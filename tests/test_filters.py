import pytest

from hbr.collectors.competitors import match_competitor
from hbr.collectors.hospital_filter import classify, is_hospital, pharma_tags

COMPS = [
    {"id": 1, "name": "SK플라즈마", "aliases": ["SK플라즈마"], "is_own": True},
    {"id": 2, "name": "GC", "aliases": ["GC", "GC녹십자", "녹십자"]},
    {"id": 3, "name": "CSL", "aliases": ["CSL", "한국씨에스엘베링"]},
    {"id": 4, "name": "JW", "aliases": ["JW", "JW중외", "중외제약"]},
]


@pytest.mark.parametrize("name,expected", [
    ("서울대학교병원", True), ("경기도의료원 수원병원", True), ("대한적십자사 서울적십자병원", True),
    ("중앙보훈병원", True), ("국립암센터", True), ("국립중앙의료원", True), ("국립공원공단", False),
    ("국립중앙박물관", False), ("OO동물병원", False), ("서울특별시청", False), ("", False), (None, False),
])
def test_is_hospital(name, expected):
    assert is_hospital(name) is expected


def test_classify():
    assert classify("서울대학교병원")["hospital_type"] == "상급종합병원"
    assert classify("서울대학교병원")["region"] == "서울"
    assert classify("중앙보훈병원")["hospital_type"] == "보훈병원"
    assert classify("경기도의료원 수원병원")["hospital_type"] == "의료원"
    assert classify("국립암센터")["hospital_type"] == "국립병원"
    assert classify("부산OO대학교병원")["region"] == "부산"


def test_pharma_tags():
    ok, tags = pharma_tags("알부민 20% 구매")
    assert ok and "알부민" in tags
    assert pharma_tags("본관 냉난방기 교체 공사") == (False, [])
    assert pharma_tags("IVIG 구매")[1] == ["면역글로불린"]


@pytest.mark.parametrize("vendor,expected", [
    ("GC녹십자", "GC"), ("(주)녹십자", "GC"), ("한국씨에스엘베링(주)", "CSL"), ("JW중외제약", "JW"),
    ("SK플라즈마(주)", "SK플라즈마"), ("지오영", None), ("GCM산업", "GC"),   # 짧은 영문은 앞부분 일치
    ("AGC글라스", None), ("", None), (None, None),
])
def test_match_competitor(vendor, expected):
    got = match_competitor(vendor, COMPS)
    assert (got["name"] if got else None) == expected
