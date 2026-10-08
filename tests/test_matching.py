import pandas as pd
import pytest

from hbr.analytics.matching import level_of, match_frame, match_product, match_text, term_in_text

ALPHA = {"id": 1, "name": "알파주", "ingredient": "Vutrisiran", "product_group": "항체", "manufacturer": "가나제약",
         "insurance_code": "123456789", "atc_code": "N07XX", "keywords": ["알파", "ALPHA-INJ"]}
ALBUMIN = {"id": 2, "name": "알부민", "ingredient": None, "product_group": "혈액제제", "manufacturer": None, "insurance_code": None,
           "atc_code": None, "keywords": ["Albumin"]}


def test_levels():
    assert [level_of(s) for s in (100, 80, 79, 55, 54, 35, 34)] == ["HIGH", "HIGH", "MEDIUM", "MEDIUM", "LOW", "LOW", None]


@pytest.mark.parametrize("term,text,ok", [
    ("alpha", "Alpha 주사 구매", True), ("alpha", "alphabet 구매", False),           # 영문은 단어 경계
    ("알부민", "알부민 20% 100mL 구매", True), ("알 부 민", "알부민 구매", True),     # 띄어쓰기 차이 허용
    ("주사", "의약품 주사제 구매", False), ("주사", "소독 주사 키트", True),           # 2글자는 앞뒤가 한글이면 불일치
    ("", "아무거나", False), (None, "x", False), ("x", None, False),
])
def test_term_in_text(term, text, ok):
    assert term_in_text(term, text) is ok


def test_name_match_is_high_with_reason():
    m = match_product(ALPHA, "[의약품] 알파주 구매")
    assert m.level == "HIGH" and m.score >= 90 and "제품명 일치(알파주)" in m.reasons and not m.needs_review


def test_ingredient_only_is_high_boundary_but_name_beats_it():
    m = match_product(ALPHA, "[의약품] Vutrisiran 구매")
    assert m.level == "HIGH" and m.reasons[0] == "성분명 일치(Vutrisiran)" and m.score == 80
    both = match_product(ALPHA, "알파주(Vutrisiran) 단가계약")
    assert both.score > match_product(ALPHA, "알파주 단가계약").score                 # 단서가 겹치면 가산


def test_keyword_and_insurance_code_signals():
    assert match_product(ALPHA, "ALPHA-INJ 주사 구매").reasons[0].startswith("동의어 일치")
    ins = match_product(ALPHA, "의약품 보험코드 123456789 단가계약")
    assert ins.score >= 95 and ins.reasons[0] == "보험코드 일치(123456789)"


def test_group_only_is_low_and_needs_review():
    m = match_product(ALBUMIN, "혈액제제 단가계약")                                      # 제품명/동의어는 없고 제품군만
    assert m.level == "LOW" and m.needs_review and m.reasons == ("제품군 일치(혈액제제)",)


def test_group_matches_classification_tags_too():
    m = match_product({**ALBUMIN, "name": "다른제품", "keywords": []}, "의약품 단가", tags=["혈액제제"])
    assert m.level == "LOW" and "제품군 일치(혈액제제)" in m.reasons


def test_fuzzy_name_for_small_spelling_difference():
    m = match_product({"id": 3, "name": "Tirabrutinib"}, "[의약품] Tirabrutnib 구매")      # 글자 하나 빠진 표기
    assert m and m.score == 60 and m.level == "MEDIUM" and "비슷한 표기" in m.reasons[0]


def test_no_match_and_false_positive_guards():
    assert match_product(ALPHA, "본관 냉난방기 교체") is None
    assert match_product({"name": "주사"}, "의약품 주사제 구매") is None                  # 2글자 이름이 더 긴 단어 안에 있으면 매칭 안 함
    assert match_product({"name": "alpha"}, "alphabet 구매") is None
    assert match_product({"name": ""}, "알파주 구매") is None


def test_match_text_sorted_and_frame_alignment():
    products = [ALPHA, ALBUMIN]
    ms = match_text(products, "알부민 20% 및 알파주 단가계약")
    assert [m.product for m in ms] == ["알파주", "알부민"] or [m.product for m in ms] == ["알부민", "알파주"]
    assert ms[0].score >= ms[1].score
    df = pd.DataFrame({"title": ["알파주 구매", "냉난방기", "알부민 구매"], "product_tags": [[], [], ["알부민"]]}, index=[10, 20, 30])
    out = match_frame(df, products)
    assert list(out.index) == [10, 20, 30]
    assert out.loc[10, "match_product"] == "알파주" and out.loc[10, "match_level"] == "HIGH"
    assert pd.isna(out.loc[20, "match_product"]) and out.loc[20, "match_count"] == 0
    assert out.loc[30, "match_product"] == "알부민"


def test_match_frame_without_products_or_rows():
    assert match_frame(pd.DataFrame(), [ALPHA]).empty
    out = match_frame(pd.DataFrame({"title": ["알파주"]}), [])
    assert out["match_count"].tolist() == [0] and out["match_product"].isna().all()                 # 제품 미등록이면 아무것도 매칭하지 않는다


def test_matches_use_only_the_given_company_products():
    """회사 A 의 제품 목록만 넘기면 회사 B 의 제품은 절대 결과에 나오지 않는다."""
    mine = [{"id": 1, "name": "가나주"}]
    other = {"id": 9, "name": "남의제품"}
    ms = match_text(mine, "남의제품 구매 가나주")
    assert [m.product for m in ms] == ["가나주"] and other["name"] not in [m.product for m in ms]


def test_rows_not_judged_as_pharma_are_capped_to_low_for_review():
    products = [{"id": 1, "name": "인플루엔자 백신", "ingredient": "인플루엔자", "product_group": "백신", "keywords": []}]
    df = pd.DataFrame({"title": ["인플루엔자 백신 구매", "[일반용역] H7N9 인플루엔자 항원 단백질 연구"], "is_pharma": [True, False],
                       "product_tags": [["백신"], ["백신"]]})
    out = match_frame(df, products)
    assert out.loc[0, "match_level"] == "HIGH"
    assert out.loc[1, "match_level"] == "LOW" and out.loc[1, "match_score"] <= 54            # 연구 용역은 HIGH 가 될 수 없다
    assert "의약품 구매로 판정되지 않은" in out.loc[1, "match_reasons"]
    no_flag = match_frame(df.drop(columns=["is_pharma"]), products)                          # 판정 열이 없으면 그대로(예: 계약 등)
    assert no_flag.loc[1, "match_level"] == "HIGH"


# ── 입찰공고 화면 (회사별 관심제품 매칭) ────────────────────────────
def _bids_page(user):
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    st_root = Path(__file__).resolve().parents[1]
    at = AppTest.from_file(str(st_root / "views/bids.py"), default_timeout=90)
    at.session_state["user"] = user
    return at.run()


def test_bids_page_shows_only_my_companys_product_matches():
    import streamlit as st

    from hbr.auth.rbac import User
    from views._common import repo

    st.cache_data.clear()
    r = repo()
    mine, other = r.create_company("매칭테스트가나"), r.create_company("매칭테스트다라")
    r.save_product(mine["id"], "면역글로불린", product_group="혈액제제")           # 데모 공고에 실제로 있는 단어
    r.save_product(other["id"], "알부민")
    try:
        at = _bids_page(User(1, "a@x.com", "a", "admin", mine["id"]))
        assert not at.exception, [e.value for e in at.exception]
        df = at.dataframe[0].value
        assert "관심제품" in df.columns
        shown = " ".join(df["관심제품"].astype(str))
        assert "면역글로불린" in shown and "알부민" not in shown                    # 다른 회사 제품은 보이지 않는다
        st.cache_data.clear()
        none = _bids_page(User(1, "b@x.com", "b", "admin", None))                  # 회사가 없으면 매칭 열도 비어 있다
        assert not none.exception and "관심제품" in none.dataframe[0].value.columns
        assert "".join(none.dataframe[0].value["관심제품"].astype(str)).strip("nan") == ""
    finally:
        st.cache_data.clear()
