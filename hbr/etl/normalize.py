"""API 원본 레코드 → 표준 행(dict). 필드명 후보는 g2b.pick 으로 흡수한다."""
from __future__ import annotations

import re
from datetime import date

from ..collectors.competitors import match_competitor
from ..collectors.g2b import clean_no, pick
from ..collectors.hospital_filter import classify, is_hospital, pharma_tags
from ..constants import DEFAULT_CONTRACT_MONTHS
from ..utils import add_months, normalize_name, parse_date, parse_dt, to_amount


def _hospital_of(row: dict, *fields: str) -> str | None:
    """후보 기관명 필드 중 병원 필터를 통과하는 첫 값 (수요기관 우선)."""
    for f in fields:
        name = row.get(f)
        if name and is_hospital(name):
            return str(name).strip()
    return None


def normalize_bid(raw: dict) -> dict | None:
    inst = _hospital_of(raw, "dminsttNm", "dmndInsttNm", "ntceInsttNm", "bidNtceInsttNm")
    if not inst:
        return None
    no = clean_no(pick(raw, "bidNtceNo"))
    if not no:
        return None
    order = clean_no(pick(raw, "bidNtceOrd", default="00")) or "00"
    title = str(pick(raw, "bidNtceNm", default="")).strip()
    is_pharma, tags = pharma_tags(title)
    deadline = parse_dt(pick(raw, "bidClseDt", "bidClseDate", "bidClseTm"))
    return {
        "bid_key": f"{no}-{order}", "bid_ntce_no": no, "bid_ntce_ord": order,
        "title": title, "inst_name": inst,
        "bid_date": parse_date(pick(raw, "bidNtceDt", "bidNtceDate", "rgstDt")),
        "deadline": deadline.isoformat() + "+09:00" if deadline else None,
        "open_date": parse_date(pick(raw, "opengDt", "opengDate")),
        "budget": to_amount(pick(raw, "asignBdgtAmt", "bdgtAmt", "presmptPrce")),
        "est_price": to_amount(pick(raw, "presmptPrce", "presmptPrceAmt")),
        "bid_method": pick(raw, "bidMethdNm", "bidMthdNm"),
        "contract_method": pick(raw, "cntrctCnclsMthdNm"),
        "url": pick(raw, "bidNtceDtlUrl", "bidNtceUrl"),
        "is_pharma": is_pharma, "product_tags": tags, "raw": raw,
    }


def normalize_award(raw: dict, competitors: list[dict]) -> dict | None:
    inst = _hospital_of(raw, "dminsttNm", "dmndInsttNm", "ntceInsttNm", "bidNtceInsttNm")
    if not inst:
        return None
    no = clean_no(pick(raw, "bidNtceNo"))
    winner = pick(raw, "bidwinnrNm", "sucsfbidCorpNm", "scsbidCorpNm", "bidwinnrCorpNm")
    if not no or not winner:
        return None
    order = clean_no(pick(raw, "bidNtceOrd", default="00")) or "00"
    biz = clean_no(pick(raw, "bidwinnrBizno", "sucsfbidBizno", "bidwinnrBizNo"))
    title = str(pick(raw, "bidNtceNm", "cntrctNm", default="")).strip()
    is_pharma, tags = pharma_tags(title)
    comp = match_competitor(winner, competitors)
    return {
        "award_key": f"{no}-{order}-{biz or normalize_name(winner)}",
        "bid_ntce_no": no, "bid_ntce_ord": order, "title": title, "inst_name": inst,
        "winner_name": str(winner).strip(), "winner_biz_no": biz or None,
        "competitor_id": comp["id"] if comp else None,
        "award_amount": to_amount(pick(raw, "sucsfbidAmt", "scsbidAmt", "bidwinnrAmt")),
        "award_rate": to_amount(pick(raw, "sucsfbidRate", "scsbidRate")),
        "award_date": parse_date(pick(raw, "rlOpengDt", "opengDt", "opengDate", "fnlSucsfDate")),
        "is_pharma": is_pharma, "product_tags": tags, "raw": raw,
    }


_PERIOD_RE = re.compile(r"(\d{4}[-./]?\d{2}[-./]?\d{2})\s*[~\-]\s*(\d{4}[-./]?\d{2}[-./]?\d{2})")


def normalize_contract(raw: dict, competitors: list[dict]) -> dict | None:
    inst = _hospital_of(raw, "dminsttNm", "cntrctInsttNm", "dmndInsttNm", "ntceInsttNm")
    if not inst:
        return None
    no = clean_no(pick(raw, "untyCntrctNo", "cntrctNo", "cntrctMngNo"))
    if not no:
        return None
    order = clean_no(pick(raw, "cntrctDegree", "cntrctOrd", default="00")) or "00"
    vendor = pick(raw, "cntrctCorpNm", "corpNm", "cnsttyNm", "cntrctPrtnrNm")
    if not vendor:                                 # corpList: "[1^단독^업체명^대표자^...]" 형태 방어
        m = re.search(r"\^([^\^\]\[]+)\^", str(pick(raw, "corpList", default="")))
        vendor = m.group(1) if m else None
    title = str(pick(raw, "cntrctNm", "bidNtceNm", default="")).strip()
    cdate = parse_date(pick(raw, "cntrctCnclsDate", "cntrctDate"))
    start = parse_date(pick(raw, "cntrctBgnDate", "cntrctStrtDate", "cntrctPrdBgnDate"))
    end = parse_date(pick(raw, "cntrctEndDate", "cntrctPrdEndDate", "ttalCntrctEndDate"))
    if not (start and end):                        # '2026.01.01 ~ 2026.12.31' 형태 텍스트
        m = _PERIOD_RE.search(str(pick(raw, "cntrctPrdCn", "cntrctPrd", default="")))
        if m:
            start, end = start or parse_date(m.group(1)), end or parse_date(m.group(2))
    start = start or cdate
    estimated = False
    if not end and start:                          # 종료일 미제공 → 추정(화면에 '추정' 표시)
        end, estimated = add_months(start, DEFAULT_CONTRACT_MONTHS), True
    is_pharma, tags = pharma_tags(title)
    comp = match_competitor(vendor, competitors)
    return {
        "contract_key": f"{no}-{order}", "contract_no": no, "title": title, "inst_name": inst,
        "vendor_name": str(vendor).strip() if vendor else None,
        "vendor_biz_no": clean_no(pick(raw, "cntrctCorpBizno", "corpBizno")) or None,
        "competitor_id": comp["id"] if comp else None,
        "contract_amount": to_amount(pick(raw, "totCntrctAmt", "thtmCntrctAmt", "cntrctAmt")),
        "contract_date": cdate, "start_date": start, "end_date": end,
        "end_date_estimated": estimated, "is_pharma": is_pharma, "product_tags": tags, "raw": raw,
    }


def hospital_row(inst_name: str) -> dict:
    return classify(inst_name)


def completeness(row: dict) -> int:
    """중복 제거 시 더 정보가 많은 행을 남기기 위한 점수."""
    return sum(1 for k, v in row.items() if k != "raw" and v not in (None, "", []))
