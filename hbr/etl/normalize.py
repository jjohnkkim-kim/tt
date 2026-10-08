"""API 원본 레코드 → 표준 행(dict). 필드명 후보는 g2b.pick 으로 흡수한다."""
from __future__ import annotations

import re
from datetime import date

from ..collectors.competitors import match_competitor
from ..collectors.g2b import clean_no, pick
from ..collectors.hospital_filter import classify, is_hospital, pharma_tags
from ..constants import DEFAULT_CONTRACT_MONTHS
from ..utils import add_months, normalize_name, parse_date, parse_dt, to_amount


# ── API 응답 필드 후보 (논리 필드 → 실제 응답 필드명 후보, 앞쪽이 우선) ──
# 실제 응답과 다르면 여기만 고친다. scripts/check_g2b_fields.py 가 이 표로 실제 응답을 점검한다.
FIELDS: dict[str, dict[str, tuple[str, ...]]] = {
    "bids": {
        "inst": ("dminsttNm", "dmndInsttNm", "ntceInsttNm", "bidNtceInsttNm"),
        "no": ("bidNtceNo",), "order": ("bidNtceOrd",), "title": ("bidNtceNm",),
        "bid_date": ("bidNtceDt", "bidNtceDate", "rgstDt"),
        "deadline": ("bidClseDt", "bidClseDate", "bidClseTm"),
        "open_date": ("opengDt", "opengDate"),
        "budget": ("asignBdgtAmt", "bdgtAmt", "presmptPrce"),
        "est_price": ("presmptPrce", "presmptPrceAmt"),
        "bid_method": ("bidMethdNm", "bidMthdNm"),
        "contract_method": ("cntrctCnclsMthdNm",),
        "url": ("bidNtceDtlUrl", "bidNtceUrl"),
    },
    "awards": {
        "inst": ("dminsttNm", "dmndInsttNm", "ntceInsttNm", "bidNtceInsttNm"),
        "no": ("bidNtceNo",), "order": ("bidNtceOrd",), "title": ("bidNtceNm", "cntrctNm"),
        "winner": ("bidwinnrNm", "sucsfbidCorpNm", "scsbidCorpNm", "bidwinnrCorpNm"),
        "biz": ("bidwinnrBizno", "sucsfbidBizno", "bidwinnrBizNo"),
        "amount": ("sucsfbidAmt", "scsbidAmt", "bidwinnrAmt"),
        "rate": ("sucsfbidRate", "scsbidRate"),
        "date": ("rlOpengDt", "opengDt", "opengDate", "fnlSucsfDate"),
    },
    "contracts": {
        "inst": ("dminsttNm", "cntrctInsttNm", "dmndInsttNm", "ntceInsttNm"),
        "no": ("untyCntrctNo", "cntrctNo", "cntrctMngNo"), "order": ("cntrctDegree", "cntrctOrd"),
        "vendor": ("cntrctCorpNm", "corpNm", "cnsttyNm", "cntrctPrtnrNm"), "vendor_list": ("corpList",),
        "title": ("cntrctNm", "bidNtceNm"),
        "contract_date": ("cntrctCnclsDate", "cntrctDate"),
        "start": ("cntrctBgnDate", "cntrctStrtDate", "cntrctPrdBgnDate"),
        "end": ("cntrctEndDate", "cntrctPrdEndDate", "ttalCntrctEndDate"),
        "period_text": ("cntrctPrdCn", "cntrctPrd"),
        "amount": ("totCntrctAmt", "thtmCntrctAmt", "cntrctAmt"),
        "biz": ("cntrctCorpBizno", "corpBizno"),
    },
}
# 없으면 행을 버리는 필드(필수) / 없으면 기능이 약해지는 필드(중요)
REQUIRED = {"bids": ("inst", "no"), "awards": ("inst", "no", "winner"), "contracts": ("inst", "no")}
IMPORTANT = {"bids": ("title", "bid_date", "deadline", "budget"),
             "awards": ("amount", "date"),
             "contracts": ("vendor", "amount", "contract_date", "end")}


def _hospital_of(row: dict, *fields: str) -> str | None:
    """후보 기관명 필드 중 병원 필터를 통과하는 첫 값 (수요기관 우선)."""
    for f in fields:
        name = row.get(f)
        if name and is_hospital(name):
            return str(name).strip()
    return None


def normalize_bid(raw: dict) -> dict | None:
    F = FIELDS["bids"]
    inst = _hospital_of(raw, *F["inst"])
    if not inst:
        return None
    no = clean_no(pick(raw, *F["no"]))
    if not no:
        return None
    order = clean_no(pick(raw, *F["order"], default="00")) or "00"
    title = str(pick(raw, *F["title"], default="")).strip()
    is_pharma, tags = pharma_tags(title)
    deadline = parse_dt(pick(raw, *F["deadline"]))
    return {
        "bid_key": f"{no}-{order}", "bid_ntce_no": no, "bid_ntce_ord": order,
        "title": title, "inst_name": inst,
        "bid_date": parse_date(pick(raw, *F["bid_date"])),
        "deadline": deadline.isoformat() + "+09:00" if deadline else None,
        "open_date": parse_date(pick(raw, *F["open_date"])),
        "budget": to_amount(pick(raw, *F["budget"])),
        "est_price": to_amount(pick(raw, *F["est_price"])),
        "bid_method": pick(raw, *F["bid_method"]),
        "contract_method": pick(raw, *F["contract_method"]),
        "url": pick(raw, *F["url"]),
        "is_pharma": is_pharma, "product_tags": tags, "raw": raw,
    }


def normalize_award(raw: dict, competitors: list[dict]) -> dict | None:
    F = FIELDS["awards"]
    inst = _hospital_of(raw, *F["inst"])
    if not inst:
        return None
    no = clean_no(pick(raw, *F["no"]))
    winner = pick(raw, *F["winner"])
    if not no or not winner:
        return None
    order = clean_no(pick(raw, *F["order"], default="00")) or "00"
    biz = clean_no(pick(raw, *F["biz"]))
    title = str(pick(raw, *F["title"], default="")).strip()
    is_pharma, tags = pharma_tags(title)
    comp = match_competitor(winner, competitors)
    return {
        "award_key": f"{no}-{order}-{biz or normalize_name(winner)}",
        "bid_ntce_no": no, "bid_ntce_ord": order, "title": title, "inst_name": inst,
        "winner_name": str(winner).strip(), "winner_biz_no": biz or None,
        "competitor_id": comp["id"] if comp else None,
        "award_amount": to_amount(pick(raw, *F["amount"])),
        "award_rate": to_amount(pick(raw, *F["rate"])),
        "award_date": parse_date(pick(raw, *F["date"])),
        "is_pharma": is_pharma, "product_tags": tags, "raw": raw,
    }


_PERIOD_RE = re.compile(r"(\d{4}[-./]?\d{2}[-./]?\d{2})\s*[~\-]\s*(\d{4}[-./]?\d{2}[-./]?\d{2})")


def normalize_contract(raw: dict, competitors: list[dict]) -> dict | None:
    F = FIELDS["contracts"]
    inst = _hospital_of(raw, *F["inst"])
    if not inst:
        return None
    no = clean_no(pick(raw, *F["no"]))
    if not no:
        return None
    order = clean_no(pick(raw, *F["order"], default="00")) or "00"
    vendor = pick(raw, *F["vendor"])
    if not vendor:                                 # corpList: "[1^단독^업체명^대표자^...]" 형태 방어
        m = re.search(r"\^([^\^\]\[]+)\^", str(pick(raw, *F["vendor_list"], default="")))
        vendor = m.group(1) if m else None
    title = str(pick(raw, *F["title"], default="")).strip()
    cdate = parse_date(pick(raw, *F["contract_date"]))
    start = parse_date(pick(raw, *F["start"]))
    end = parse_date(pick(raw, *F["end"]))
    if not (start and end):                        # '2026.01.01 ~ 2026.12.31' 형태 텍스트
        m = _PERIOD_RE.search(str(pick(raw, *F["period_text"], default="")))
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
        "vendor_biz_no": clean_no(pick(raw, *F["biz"])) or None,
        "competitor_id": comp["id"] if comp else None,
        "contract_amount": to_amount(pick(raw, *F["amount"])),
        "contract_date": cdate, "start_date": start, "end_date": end,
        "end_date_estimated": estimated, "is_pharma": is_pharma, "product_tags": tags, "raw": raw,
    }


def hospital_row(inst_name: str) -> dict:
    return classify(inst_name)


def completeness(row: dict) -> int:
    """중복 제거 시 더 정보가 많은 행을 남기기 위한 점수."""
    return sum(1 for k, v in row.items() if k != "raw" and v not in (None, "", []))
