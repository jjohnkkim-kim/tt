from datetime import date

import pandas as pd

from hbr.analytics.competitors import coverage, hospital_share, prepare, vendor_detail, vendor_ranking

T = pd.Timestamp


def row(no, winner, d, hosp=1, biz=None, amount=1e7, hospital="A병원", tags=()):
    return {"bid_ntce_no": no, "bid_ntce_ord": "000", "winner_name": winner, "winner_biz_no": biz, "award_date": T(d), "hospital_id": hosp,
            "hospital": hospital, "award_amount": amount, "product_tags": list(tags), "is_pharma": True}


def frame(rows):
    return prepare(pd.DataFrame(rows))


def test_vendors_with_different_spellings_or_same_biz_no_are_one_vendor():
    df = frame([row("1", "(주)가나제약", "2026-10-01", biz="123-45-67890"), row("2", "가나제약 주식회사", "2026-10-02", biz="1234567890"),
                row("3", "(주)다라바이오", "2026-10-03"), row("4", "다라바이오", "2026-10-04")])
    assert df["vendor_key"].nunique() == 2                                   # 사업자번호가 같으면 하나, 이름은 (주) 차이 흡수
    assert sorted(df.groupby("vendor_key").size().tolist()) == [2, 2]


def test_duplicate_rows_of_one_bid_count_once():
    df = frame([row("1", "가나제약", "2026-10-01"), row("1", "가나제약", "2026-10-01"), row("2", "가나제약", "2026-10-02")])
    assert len(df) == 2


def test_prepare_handles_empty_and_failed_rows():
    assert prepare(pd.DataFrame()).empty and prepare(None).empty
    assert frame([{**row("1", None, "2026-10-01")}]).empty                    # 낙찰업체가 없는 행(유찰)은 제외


def test_ranking_counts_amount_hospitals_and_change_against_previous_period():
    df = frame([row("1", "가나", "2026-10-05", hosp=1, amount=3e7), row("2", "가나", "2026-10-06", hosp=2, amount=1e7),
                row("3", "다라", "2026-10-07", hosp=1, amount=5e7),
                row("4", "가나", "2026-09-28", hosp=1), row("5", "가나", "2026-09-29", hosp=1), row("6", "가나", "2026-09-30", hosp=1)])   # 직전 기간
    rk = vendor_ranking(df, date(2026, 10, 1), date(2026, 10, 7), own_aliases=["다라"])
    ga, da = rk[rk["업체"] == "가나"].iloc[0], rk[rk["업체"] == "다라"].iloc[0]
    assert (ga["낙찰 건수"], ga["낙찰 병원 수"], ga["직전 기간 건수"], ga["변화"]) == (2, 2, 3, -1)
    assert ga["낙찰 금액"] == 4e7 and not ga["자사"] and da["자사"]
    assert list(rk["업체"]) == ["가나", "다라"]                                # 건수 순
    assert vendor_ranking(df, date(2025, 1, 1), date(2025, 1, 7)).empty
    assert vendor_ranking(pd.DataFrame(), date(2026, 10, 1), date(2026, 10, 7)).empty


def test_vendor_detail_breakdowns():
    df = frame([row("1", "가나", "2026-09-05", hospital="A병원", tags=["백신"]), row("2", "가나", "2026-10-05", hospital="B병원", tags=["백신", "수액"]),
                row("3", "가나", "2026-10-06", hospital="B병원"), row("4", "다라", "2026-10-06")])
    key = df[df["vendor"] == "가나"]["vendor_key"].iloc[0]
    d = vendor_detail(df, key, date(2026, 9, 1), date(2026, 10, 31))
    assert d["total"] == 3 and list(d["by_hospital"]["hospital"]) == ["B병원", "A병원"]
    assert list(d["monthly"]["건수"]) == [1, 2] and dict(zip(d["tags"]["분류"], d["tags"]["건수"])) == {"백신": 2, "수액": 1}
    assert vendor_detail(df, "none", date(2026, 9, 1), date(2026, 10, 31))["empty"]


def test_hospital_share_basis_sample_size_and_other_bucket():
    rows = [row(str(i), f"업체{i % 8}", "2026-10-01") for i in range(16)]            # 8개 업체가 2건씩
    df = frame(rows)
    sh = hospital_share(df, 1, date(2026, 10, 1), date(2026, 10, 7), top=3)
    assert sh["basis"] == "낙찰 건수" and sh["n"] == 16 and sh["sufficient"]
    t = sh["table"]
    assert len(t) == 4 and t.iloc[-1]["업체"] == "기타 5곳" and abs(t["비중(%)"].sum() - 100) < 0.2
    small = hospital_share(frame([row("1", "가나", "2026-10-01"), row("2", "다라", "2026-10-02")]), 1, date(2026, 10, 1), date(2026, 10, 7))
    assert small["n"] == 2 and not small["sufficient"]                           # 표본 부족을 알린다
    empty = hospital_share(df, 999, date(2026, 10, 1), date(2026, 10, 7))
    assert empty["n"] == 0 and empty["table"].empty and not empty["sufficient"]


def test_hospital_share_by_amount_and_zero_amounts():
    df = frame([row("1", "가나", "2026-10-01", amount=9e7), row("2", "다라", "2026-10-02", amount=1e7)])
    sh = hospital_share(df, 1, date(2026, 10, 1), date(2026, 10, 7), by="amount")
    assert sh["basis"] == "낙찰 금액" and list(sh["table"]["비중(%)"]) == [90.0, 10.0]
    none = hospital_share(frame([row("1", "가나", "2026-10-01", amount=None)]), 1, date(2026, 10, 1), date(2026, 10, 7), by="amount")
    assert none["table"].empty                                                   # 금액이 없으면 비중을 만들어 내지 않는다


def test_coverage():
    df = frame([row("1", "가나", "2026-09-05"), row("2", "가나", "2026-10-05")])
    assert coverage(df) == (date(2026, 9, 5), date(2026, 10, 5)) and coverage(pd.DataFrame()) == (None, None)
