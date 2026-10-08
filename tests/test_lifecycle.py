from datetime import date

import pandas as pd
import pytest

from hbr.analytics.data import Snapshot
from hbr.analytics.lifecycle import BASIS_GUESS, build_lifecycle, core_title, hospital_timeline, is_rebid_title

TODAY = date(2026, 10, 8)
T = pd.Timestamp


def bid(no, title, bid_date, deadline, open_date=None, hosp=1, **kw):
    return {"bid_ntce_no": no, "bid_ntce_ord": "000", "title": title, "hospital_id": hosp, "bid_date": T(bid_date),
            "deadline": T(deadline) if deadline else pd.NaT, "open_date": T(open_date) if open_date else pd.NaT, "budget": 1e8, **kw}


def result(no, status, date_, title="t", hosp=1, winner="제약", amount=1e7, **kw):
    return {"bid_ntce_no": no, "bid_ntce_ord": "000", "title": title, "hospital_id": hosp, "award_date": T(date_),
            "result_status": status, "winner_name": winner if status == "낙찰" else None, "award_amount": amount if status == "낙찰" else None, **kw}


def snap(bids, awards=(), failed=(), contracts=()):
    f = lambda rows: pd.DataFrame(list(rows))
    return Snapshot(pd.DataFrame(), pd.DataFrame(), f(bids), f(awards), f(contracts), f(failed))


def test_core_title_strips_rebid_markers_but_keeps_group_labels():
    assert core_title("(재공고)(확대공고-2차)(본·분원 통합입찰) 2026년 직원용 독감백신 공급계약") == core_title("(긴급)(새로운입찰)(본·분원 통합입찰) 2026년 직원용 독감백신 공급계약")
    assert core_title("[의약품] 단가 계약(1그룹)") != core_title("[의약품] 단가 계약(3그룹)")      # 그룹이 다르면 다른 입찰
    assert is_rebid_title("(재공고)의약품 단가") and is_rebid_title("(긴급)(새로운입찰)백신") and not is_rebid_title("의약품 단가")


def test_rebid_word_without_parentheses_is_stripped():
    assert core_title("2026년 의약품 통합구매(A) 재공고") == core_title("2026년 의약품 통합구매(A)")
    assert core_title("2026년 의약품 통합구매(A) 재공고") != core_title("2026년 의약품 통합구매(B)")       # 구분 괄호는 그대로


def test_parentheses_that_identify_the_item_are_kept():
    a = core_title("[재공고] 2026년 서울특별시 의료장비 통합구매(서울의료원, 카트세척기)")
    b = core_title("2026년 서울특별시 의료장비 통합구매(보라매병원, 신생아소아용인공호흡기)")
    assert a != b                                                     # 품목이 다르면 같은 입찰이 아니다
    assert core_title("(재공고)(확대공고-2차)(본·분원 통합입찰) 독감백신") == core_title("(긴급)(새로운입찰)(본·분원 통합입찰) 독감백신")
    assert core_title("(재공고)의료장비 대장내시경 2SET") == core_title("(긴급)의료장비 대장내시경 2SET")


def test_different_equipment_in_same_framework_title_is_not_linked():
    failed = [result("OLD", "유찰", "2026-10-02", title="2026년 서울특별시 의료장비 통합구매(서울의료원, 카트세척기)", hosp=1)]
    b = [bid("NEW", "[재공고] 2026년 서울특별시 의료장비 통합구매(서울의료원, 심전도검사기)", "2026-10-06", "2026-10-20")]
    assert pd.isna(build_lifecycle(snap(b, failed=failed), TODAY).iloc[0]["prev_ntce_no"])


def test_status_rules():
    b = [bid("N", "신규", "2026-10-08", "2026-10-20"), bid("P", "진행중", "2026-10-01", "2026-10-20"),
         bid("W", "개찰대기", "2026-10-01", "2026-10-07", open_date="2026-10-09"), bid("C", "마감", "2026-10-01", "2026-10-05", open_date="2026-10-06"),
         bid("A", "낙찰", "2026-10-01", "2026-10-05"), bid("F", "유찰", "2026-10-01", "2026-10-05"),
         bid("K", "계약", "2026-10-01", "2026-10-05"), bid("R", "(재공고)진행", "2026-10-01", "2026-10-20")]
    s = snap(b, awards=[result("A", "낙찰", "2026-10-06"), result("K", "낙찰", "2026-10-06")], failed=[result("F", "유찰", "2026-10-06")],
             contracts=[{"hospital_id": 1, "title": "c", "vendor_name": "제약", "contract_amount": 5e6, "contract_date": T("2026-10-07"),
                         "raw": {"bidNtceNo": "K"}}])
    lc = build_lifecycle(s, TODAY)
    got = dict(zip([x["bid_ntce_no"] for x in b], lc["status"]))
    assert got == {"N": "신규", "P": "진행중", "W": "개찰예정", "C": "마감", "A": "낙찰", "F": "유찰", "K": "계약완료", "R": "재공고"}
    assert lc.loc[lc.index[4], "winner_name"] == "제약" and lc.loc[lc.index[6], "contract_vendor"] == "제약"
    assert pd.isna(lc.loc[lc.index[0], "result_status"]) and pd.isna(lc.loc[lc.index[0], "contract_count"])       # 근거 없으면 비워 둔다


def test_winner_beats_failed_when_both_exist_for_a_bid():
    s = snap([bid("A", "x", "2026-10-01", "2026-10-05")], awards=[result("A", "낙찰", "2026-10-06")], failed=[result("A", "유찰", "2026-10-05")])
    assert build_lifecycle(s, TODAY).iloc[0]["status"] == "낙찰"


def test_rebid_links_to_previous_failed_as_a_guess_only():
    failed = [result("OLD", "유찰", "2026-09-15", title="[의약품] 독감백신 공급계약", hosp=1),
              result("OTHERHOSP", "유찰", "2026-09-16", title="독감백신 공급계약", hosp=2),
              result("OTHERGROUP", "유찰", "2026-09-17", title="독감백신 공급계약(3그룹)", hosp=1)]
    b = [bid("NEW", "(재공고)독감백신 공급계약(1그룹)", "2026-10-02", "2026-10-20", hosp=1),
         bid("NEW2", "(재공고)독감백신 공급계약", "2026-10-02", "2026-10-20", hosp=1),
         bid("LATER", "(재공고)독감백신 공급계약", "2026-09-10", "2026-10-20", hosp=1)]            # 유찰보다 먼저 나온 공고는 연결 안 함
    lc = build_lifecycle(snap(b, failed=failed), TODAY)
    assert pd.isna(lc.iloc[0]["prev_ntce_no"])                                 # (1그룹) ≠ (3그룹) ≠ 그룹 없음 → 연결 근거 없음
    assert lc.iloc[1]["prev_ntce_no"] == "OLD" and lc.iloc[1]["prev_basis"] == BASIS_GUESS and lc.iloc[1]["prev_status"] == "유찰"
    assert pd.isna(lc.iloc[2]["prev_ntce_no"])
    assert lc.iloc[1]["prev_date"] == T("2026-09-15")                          # 다른 병원(OTHERHOSP)은 연결되지 않는다


def test_non_rebid_never_gets_a_previous_link():
    s = snap([bid("NEW", "독감백신 공급계약", "2026-10-02", "2026-10-20")], failed=[result("OLD", "유찰", "2026-09-15", title="독감백신 공급계약")])
    assert pd.isna(build_lifecycle(s, TODAY).iloc[0]["prev_ntce_no"])


def test_similar_titles_with_different_numbers_are_not_linked():
    failed = [result("OLD", "유찰", "2026-09-15", title="의약품 53종 추가단가계약")]
    b = [bid("NEW", "(재공고)의약품 52종 추가단가계약", "2026-10-02", "2026-10-20"), bid("NEW2", "(재공고)의약품 53종 추가단가계약 ", "2026-10-02", "2026-10-20")]
    lc = build_lifecycle(snap(b, failed=failed), TODAY)
    assert pd.isna(lc.iloc[0]["prev_ntce_no"]) and lc.iloc[1]["prev_ntce_no"] == "OLD"


def test_empty_snapshot_is_safe():
    assert build_lifecycle(snap([]), TODAY).empty


def test_hospital_timeline_orders_and_labels_missing_contract_end():
    s = snap([bid("B1", "공고", "2026-10-01", "2026-10-20", hosp=1), bid("B2", "다른병원", "2026-10-02", "2026-10-20", hosp=2)],
             awards=[result("A1", "낙찰", "2026-10-05", hosp=1)], failed=[result("F1", "유찰", "2026-09-20", hosp=1)],
             contracts=[{"hospital_id": 1, "title": "계약", "vendor_name": "제약", "contract_amount": 2e8, "contract_date": T("2026-10-07"),
                         "end_date": pd.NaT, "raw": {"bidNtceNo": "A1"}}])
    tl = hospital_timeline(s, 1)
    assert list(tl["구분"]) == ["계약", "낙찰", "공고", "유찰"] and "B2" not in set(tl["공고번호"])
    assert "종료일 정보 없음" in tl.iloc[0]["내용"] and tl.iloc[0]["공고번호"] == "A1"
