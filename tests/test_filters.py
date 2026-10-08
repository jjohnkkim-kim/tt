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


# ── 의약품 구매 공고 판별 (실제 수집 데이터에서 나온 사례) ─────────────
@pytest.mark.parametrize("title,division", [
    ("[의약품] Vutrisiran 구매", "물품"),
    ("[의약품] Tirabrutinib 외 11품목", "물품"),
    ("의약품 단가 계약(3그룹)", "물품"),
    ("(재공고)의약품 성분명 Joins-F Tab 300 mg 외 1종 단가계약(1그룹)", "물품"),
    ("[조영제] iopamidol 61.24g(0.6124g/mL) 외 2건(2차)", "물품"),
    ("2026년 10월 로비큐아정 25mg 단가계약", "물품"),          # 제목에 '의약품'이 없어도 용량 표기로 잡는다
    ("2026년 성남시의료원 인플루엔자 백신 구매", "물품"),
    ("알부민 20% 100mL 구매", "물품"),
])
def test_real_drug_purchases_are_pharma(title, division):
    assert pharma_tags(title, division=division)[0] is True


@pytest.mark.parametrize("title,division", [
    ("[일반용역](유찰수의,협상)(전자시담)결핵 백신 효능평가를 위한 시스템 혈청학 분석", "용역"),   # 연구 용역
    ("라싸 바이러스 재조합 단백질 백신 후보물질 생산 및 최적화", "용역"),
    ("항암제 조제 로봇 시스템 구입", "물품"),                                                  # 장비
    ("약제부 전동식 의약품 혼합용 기구 1SET", "물품"),
    ("[진단검사의학과] 의료장비(혈액 자동분석기) 구매(수정)", "물품"),
    ("2026 진단검사실 검사시약 구입(재공고)", "물품"),
    ("일회용 주사기 구매", "물품"),
    ("딥러닝 서버 16GB 구매", "물품"),                                                         # 'GB'는 용량 표기가 아니다
    ("본관 냉난방기 교체 공사", "공사"),
])
def test_equipment_research_and_construction_are_not_pharma(title, division):
    assert pharma_tags(title, division=division) == (False, [])


def test_division_is_optional_and_blood_word_alone_is_not_a_blood_product():
    assert pharma_tags("혈액제제 구매")[1] == ["혈액제제"]
    assert pharma_tags("혈액 자동분석기 구매")[0] is False
