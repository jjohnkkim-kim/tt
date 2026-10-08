import pandas as pd
import pytest

from hbr.analytics.data import load_snapshot
from hbr.collectors.competitors import matches_any_alias
from hbr.store.repo import clean_list


def test_company_create_validates_and_defaults_aliases(repo):
    c = repo.create_company("가나제약", "제약사")
    assert c["own_aliases"] == ["가나제약"]                                    # 별칭을 안 넣으면 회사명이 자사 표기명
    with pytest.raises(ValueError):
        repo.create_company("  ")
    with pytest.raises(ValueError):
        repo.create_company("가나제약")                                        # 같은 이름(대소문자 무시) 중복 불가
    repo.update_company(c["id"], "가나제약", "CSO", ["가나제약", "가나 제약(주)", "가나제약"])
    got = repo.get_company(c["id"])
    assert got["company_type"] == "CSO" and got["own_aliases"] == ["가나제약", "가나 제약(주)"]
    with pytest.raises(ValueError):
        repo.update_company(repo.create_company("다라바이오")["id"], "가나제약", "제약사", [])


def test_products_are_isolated_per_company(repo):
    a, b = repo.create_company("가나제약"), repo.create_company("다라바이오")
    repo.save_product(a["id"], "알파주", ingredient="알파성분", product_group="항체", keywords="알파, ALPHA")
    repo.save_product(b["id"], "알파주", ingredient="다른성분")                 # 다른 회사의 같은 제품명은 따로 저장
    repo.save_product(b["id"], "베타정")
    assert [p["name"] for p in repo.list_products(a["id"])] == ["알파주"]
    assert sorted(p["name"] for p in repo.list_products(b["id"])) == ["베타정", "알파주"]
    assert repo.list_products(a["id"])[0]["ingredient"] == "알파성분" and repo.list_products(a["id"])[0]["keywords"] == ["알파", "ALPHA"]
    # 제품명으로 수정(upsert)해도 다른 회사 행은 그대로
    repo.save_product(a["id"], "알파주", ingredient="수정됨")
    assert [p["ingredient"] for p in repo.list_products(a["id"])] == ["수정됨"]
    assert [p["ingredient"] for p in repo.list_products(b["id"]) if p["name"] == "알파주"] == ["다른성분"]
    assert repo.list_products(None) == [] and repo.list_products(99999) == []   # 회사가 없거나 모르면 아무것도 안 보인다


def test_delete_product_cannot_touch_another_company(repo):
    a, b = repo.create_company("가나제약"), repo.create_company("다라바이오")
    pa = repo.save_product(a["id"], "알파주")
    repo.delete_product(b["id"], pa["id"])                                     # 다른 회사 번호로는 지워지지 않는다
    assert len(repo.list_products(a["id"])) == 1
    repo.delete_product(a["id"], pa["id"])
    assert repo.list_products(a["id"]) == []


def test_save_product_requires_company_and_name(repo):
    c = repo.create_company("가나제약")
    with pytest.raises(ValueError):
        repo.save_product(None, "알파주")
    with pytest.raises(ValueError):
        repo.save_product(c["id"], "  ")


def test_assign_company_and_aliases_lookup(repo):
    c = repo.create_company("가나제약", own_aliases=["가나제약", "GANA"])
    u = repo.ensure_user("a@x.com", "a", "viewer")
    repo.assign_company(u["id"], c["id"])
    assert repo.get_user("a@x.com")["company_id"] == c["id"]
    assert repo.own_aliases(c["id"]) == ["가나제약", "GANA"] and repo.own_aliases(None) == []
    repo.assign_company(u["id"], None)
    assert repo.get_user("a@x.com")["company_id"] is None


def test_matches_any_alias_rules():
    assert matches_any_alias("가나제약(주)", ["가나제약"]) and matches_any_alias("(주)가나제약", ["가나제약"])
    assert not matches_any_alias("다라바이오", ["가나제약"]) and not matches_any_alias("가나제약", []) and not matches_any_alias(None, ["가나제약"])
    assert matches_any_alias("GNA PHARM", ["GNA"]) and not matches_any_alias("XGNA", ["GNA"])         # 3글자 이하 영문은 앞부분 일치만


def test_snapshot_marks_own_awards_by_company_aliases_not_hardcoded(repo):
    hid = repo.upsert_hospitals([{"name": "테스트병원", "name_norm": "테스트병원", "hospital_type": "병원", "is_active": True}])["테스트병원"]
    base = {"hospital_id": hid, "inst_name": "테스트병원", "title": "의약품", "is_pharma": True, "award_date": "2026-10-01", "result_status": "낙찰"}
    repo.upsert("awards", [{**base, "award_key": "1", "bid_ntce_no": "1", "winner_name": "가나제약(주)"},
                           {**base, "award_key": "2", "bid_ntce_no": "2", "winner_name": "SK플라즈마"}])
    own = lambda aliases: dict(zip(load_snapshot(repo, aliases).awards["winner_name"], load_snapshot(repo, aliases).awards["is_own"]))
    assert own([]) == {"가나제약(주)": False, "SK플라즈마": False}                       # 회사가 정해지지 않으면 누구도 자사가 아니다
    assert own(["가나제약"]) == {"가나제약(주)": True, "SK플라즈마": False}
    assert own(["SK플라즈마"]) == {"가나제약(주)": False, "SK플라즈마": True}            # 어느 회사든 자기 이름만 등록하면 된다


def test_clean_list():
    assert clean_list("a, b,\nA, ,c") == ["a", "b", "c"] and clean_list(None) == [] and clean_list(["x", " x "]) == ["x"]


# ── 관심 제품 표 동기화 (설정 화면의 '저장' 버튼) ─────────────────────
def test_sync_products_adds_updates_renames_and_deletes(repo):
    from hbr.company import products_frame, sync_products

    c = repo.create_company("가나제약")
    other = repo.create_company("다라바이오")
    repo.save_product(other["id"], "남의제품")
    saved, errs = sync_products(repo, c["id"], [{"제품명": "알파주", "성분명": "알파", "동의어(쉼표 구분)": "알파, ALPHA"}, {"제품명": "베타정"}, {"제품명": "  "}])
    assert (saved, errs) == (2, [])
    frame = products_frame(repo.list_products(c["id"]))
    assert list(frame["제품명"]) == ["베타정", "알파주"] and frame.loc[frame["제품명"] == "알파주", "동의어(쉼표 구분)"].iloc[0] == "알파, ALPHA"
    recs = frame.to_dict("records")
    for r in recs:                                            # 알파주 → 이름 변경, 베타정 → 표에서 삭제
        if r["제품명"] == "알파주":
            r["제품명"], r["성분명"] = "알파플러스주", "새성분"
    saved, errs = sync_products(repo, c["id"], [r for r in recs if r["제품명"] != "베타정"])
    assert saved == 1 and errs == []
    now = repo.list_products(c["id"])
    assert [(p["name"], p["ingredient"]) for p in now] == [("알파플러스주", "새성분")]
    assert [p["name"] for p in repo.list_products(other["id"])] == ["남의제품"]            # 다른 회사 제품은 그대로


def test_sync_products_never_touches_other_companys_rows(repo):
    from hbr.company import sync_products

    c, other = repo.create_company("가나제약"), repo.create_company("다라바이오")
    repo.save_product(c["id"], "알파주")
    theirs = repo.save_product(other["id"], "남의제품", ingredient="비밀성분")
    saved, errs = sync_products(repo, c["id"], [{"id": theirs["id"], "제품명": "탈취시도"}])   # 남의 제품 id 를 넣어도
    assert errs == [] and [p["name"] for p in repo.list_products(c["id"])] == ["탈취시도"]     # 내 회사에 새 제품으로만 들어간다
    assert [(p["name"], p["ingredient"]) for p in repo.list_products(other["id"])] == [("남의제품", "비밀성분")]


def test_sync_products_skips_deletion_when_any_row_has_an_error(repo):
    from hbr.company import sync_products

    c = repo.create_company("가나제약")
    p1, p2, p3 = (repo.save_product(c["id"], n) for n in ("알파주", "베타정", "감마액"))
    saved, errs = sync_products(repo, c["id"], [{"id": p1["id"], "제품명": "새이름"}, {"id": p2["id"], "제품명": "새이름"}])   # 같은 이름 두 개 → 오류
    assert errs and "새이름" in errs[0]
    assert "감마액" in {p["name"] for p in repo.list_products(c["id"])}                    # 표에서 빠진 감마액도 오류가 있으면 삭제하지 않는다
