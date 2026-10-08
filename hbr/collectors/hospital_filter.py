"""기관명 → 병원 판별/분류."""
from __future__ import annotations

import re

from ..constants import (HOSPITAL_EXCLUDE, HOSPITAL_KEYWORDS, KNOWN_TERTIARY, NATIONAL_MEDICAL_HINTS,
                         NATIONAL_PREFIX, PHARMA_DOSE_PATTERN, PHARMA_KEYWORDS, PHARMA_NEGATIVE_DIVISIONS,
                         PHARMA_NEGATIVE_WORDS, PHARMA_STRONG_PATTERNS, PRODUCT_TAGS, REGION_PREFIXES)
from ..utils import normalize_name


def is_hospital(name: str | None) -> bool:
    if not name:
        return False
    n = normalize_name(name)
    if any(x in n for x in HOSPITAL_EXCLUDE):
        return False
    if any(k in n for k in HOSPITAL_KEYWORDS):
        return True
    return NATIONAL_PREFIX in n and any(h in n for h in NATIONAL_MEDICAL_HINTS)


def classify(name: str) -> dict:
    """병원 구분·지역 추정. 알려진 상급종합은 목록으로, 나머지는 명칭 규칙으로."""
    n = normalize_name(name)
    known = next((k for k in KNOWN_TERTIARY if normalize_name(k) in n), None)
    if known:
        htype, region = "상급종합병원", KNOWN_TERTIARY[known]
    else:
        region = next((v for k, v in REGION_PREFIXES.items() if n.startswith(k)), None)
        if "보훈" in n:
            htype = "보훈병원"
        elif "적십자" in n:
            htype = "적십자병원"
        elif n.startswith(NATIONAL_PREFIX) and "대학교병원" not in n:
            htype = "국립병원"
        elif "대학교병원" in n or "대학병원" in n or "의과대학" in n:
            htype = "대학병원"
        elif "의료원" in n:
            htype = "의료원"
        elif "종합병원" in n:
            htype = "종합병원"
        else:
            htype = "병원"
    return {"name": name.strip(), "name_norm": n, "hospital_type": htype, "region": region, "is_active": True}


def pharma_tags(*texts: str | None, division: str | None = None) -> tuple[bool, list[str]]:
    """제목 등에서 '의약품 구매' 공고 여부와 제품군 태그를 추출.

    1) 업무구분이 용역/공사면 아니다 (연구 용역, 설치 공사 등)
    2) '[의약품]', '의약품 단가', '성분명' 처럼 확실한 표현이 있으면 의약품이다
    3) 장비·기구·시약·재료 같은 말이 있으면 아니다 (항암제 조제 로봇, 혈액 분석기 등)
    4) 의약품 단어/제품군 키워드 또는 용량 표기(25mg 등)가 있으면 의약품이다
    """
    blob = " ".join(t for t in texts if t)
    blob_l = blob.lower()
    tags = [tag for tag, kws in PRODUCT_TAGS.items() if any(k.lower() in blob_l for k in kws)]
    dose = re.search(PHARMA_DOSE_PATTERN, blob, re.I) is not None
    if dose and not tags:
        tags = ["의약품(일반)"]
    keyword = bool(tags) or any(k in blob for k in PHARMA_KEYWORDS)

    if division and any(d in division for d in PHARMA_NEGATIVE_DIVISIONS):
        return False, []
    if any(re.search(p, blob) for p in PHARMA_STRONG_PATTERNS):
        return True, tags or ["의약품(일반)"]
    if any(w.lower() in blob_l for w in PHARMA_NEGATIVE_WORDS):
        return False, []
    return keyword, tags
