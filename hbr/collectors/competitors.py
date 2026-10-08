"""낙찰/계약 업체명 → 경쟁사 매칭."""
from __future__ import annotations

import re

from ..utils import normalize_name


def _short_latin(alias: str) -> bool:
    return len(alias) <= 3 and bool(re.fullmatch(r"[A-Za-z]+", alias))


def match_competitor(vendor: str | None, competitors: list[dict]) -> dict | None:
    """별칭 매칭. 영문 3자 이하(GC, JW, CSL)는 상호 앞부분 일치만 인정(오탐 방지)."""
    n = normalize_name(vendor)
    if not n:
        return None
    for c in competitors:
        for alias in c.get("aliases") or []:
            a = normalize_name(alias)
            if not a:
                continue
            if _short_latin(alias):
                if n.startswith(a):
                    return c
            elif a in n:
                return c
    return None
