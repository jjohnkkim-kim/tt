"""관심 제품 ↔ 입찰/낙찰/계약 매칭 (신뢰도 포함).

현재 입력은 '제목' 뿐이므로 제목 안의 단서(제품명·성분명·동의어·보험코드·ATC·제품군)로 점수를 낸다.
입찰 품목표/첨부파일이 확보되면 같은 함수에 그 텍스트를 함께 넘기면 된다.
점수는 사실이 아니라 '추정 신뢰도'이며 근거(어떤 단서가 맞았는지)를 항상 같이 돌려준다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

import pandas as pd

# 단서별 기본 점수
S_INSURANCE, S_NAME, S_INGREDIENT, S_KEYWORD, S_FUZZY, S_ATC, S_GROUP = 95, 90, 80, 75, 60, 60, 40
BONUS_EXTRA_SIGNAL, BONUS_MAKER, BONUS_CAP = 5, 5, 10
LEVELS = (("HIGH", 80), ("MEDIUM", 55), ("LOW", 35))
MIN_SCORE = 35
FUZZY_MIN_RATIO, FUZZY_MIN_LEN = 0.9, 5

_ASCII = re.compile(r"[\x00-\x7f]+")


@dataclass(frozen=True)
class Match:
    product_id: int | None
    product: str
    score: int
    level: str
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def needs_review(self) -> bool:
        return self.level == "LOW"


def level_of(score: int) -> str | None:
    for name, floor in LEVELS:
        if score >= floor:
            return name
    return None


def term_in_text(term, text) -> bool:
    """단어 경계를 지키는 포함 검사. 영문은 알파벳·숫자 경계, 한글 2글자는 앞뒤가 한글이 아닐 때만 인정."""
    t = str(term or "").strip().lower()
    s = str(text or "").lower()
    if not t or not s:
        return False
    if _ASCII.fullmatch(t):
        return re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", s) is not None
    compact = t.replace(" ", "")
    pat = r"\s*".join(re.escape(ch) for ch in compact)               # 글자 사이 띄어쓰기 차이는 허용
    if len(compact) >= 3:
        return re.search(pat, s) is not None
    return re.search(rf"(?<![가-힣a-z0-9]){pat}(?![가-힣a-z0-9])", s) is not None


def _tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^0-9A-Za-z가-힣]+", str(text or "").lower()) if len(t) >= FUZZY_MIN_LEN]


def _fuzzy_hit(name: str, text: str) -> bool:
    n = re.sub(r"\s+", "", str(name or "").lower())
    if len(n) < FUZZY_MIN_LEN:
        return False
    return any(SequenceMatcher(None, n, t).ratio() >= FUZZY_MIN_RATIO for t in _tokens(text))


def match_product(product: dict, text: str, tags=()) -> Match | None:
    """제품 하나와 텍스트(+분류 태그) 하나의 매칭. 근거가 없으면 None."""
    tags_text = " ".join(str(t) for t in (tags or []))
    haystack = f"{text or ''} {tags_text}"
    signals: list[tuple[int, str]] = []

    def add(score: int, label: str):
        signals.append((score, label))

    name = product.get("name")
    if term_in_text(name, text):
        add(S_NAME, f"제품명 일치({name})")
    elif _fuzzy_hit(name, text):
        add(S_FUZZY, f"제품명과 비슷한 표기({name})")
    if product.get("ingredient") and term_in_text(product["ingredient"], text):
        add(S_INGREDIENT, f"성분명 일치({product['ingredient']})")
    for kw in product.get("keywords") or []:
        if term_in_text(kw, text):
            add(S_KEYWORD, f"동의어 일치({kw})")
            break
    if product.get("insurance_code") and str(product["insurance_code"]).strip() and str(product["insurance_code"]).strip().lower() in str(text or "").lower():
        add(S_INSURANCE, f"보험코드 일치({product['insurance_code']})")
    if product.get("atc_code") and term_in_text(product["atc_code"], text):
        add(S_ATC, f"ATC 일치({product['atc_code']})")
    if product.get("product_group") and term_in_text(product["product_group"], haystack):
        add(S_GROUP, f"제품군 일치({product['product_group']})")
    if not signals:
        return None

    best = max(s for s, _ in signals)
    distinct = {label.split("(")[0] for _, label in signals}
    bonus = min(BONUS_CAP, BONUS_EXTRA_SIGNAL * (len(distinct) - 1))                  # 서로 다른 단서가 겹치면 가산
    reasons = [label for _, label in sorted(signals, key=lambda x: -x[0])]
    if best >= S_KEYWORD and product.get("manufacturer") and term_in_text(product["manufacturer"], text):
        bonus = min(BONUS_CAP, bonus + BONUS_MAKER)
        reasons.append(f"제조사 일치({product['manufacturer']})")
    score = min(100, best + bonus)
    level = level_of(score)
    if level is None:
        return None
    return Match(product.get("id"), str(name), int(score), level, tuple(reasons))


def match_text(products: list[dict], text: str, tags=()) -> list[Match]:
    """텍스트 하나에 대해 회사의 모든 제품과 매칭. 신뢰도 높은 순."""
    out = [m for p in products if (m := match_product(p, text, tags))]
    return sorted(out, key=lambda m: (-m.score, m.product))


NOT_PHARMA_CAP = 54          # 의약품 구매로 판정되지 않은 행(연구 용역·장비 등)은 최대 LOW(검토 필요)
NOT_PHARMA_NOTE = "의약품 구매로 판정되지 않은 공고라 신뢰도를 낮췄습니다"


def _cap_not_pharma(m: Match) -> Match:
    if m.score <= NOT_PHARMA_CAP:
        return Match(m.product_id, m.product, m.score, m.level, (*m.reasons, NOT_PHARMA_NOTE))
    return Match(m.product_id, m.product, NOT_PHARMA_CAP, "LOW", (*m.reasons, NOT_PHARMA_NOTE))


def match_frame(df: pd.DataFrame, products: list[dict], text_col: str = "title", tag_col: str = "product_tags",
                pharma_col: str = "is_pharma") -> pd.DataFrame:
    """df 의 각 행을 매칭한 결과 표 (df 와 같은 인덱스).

    열: match_product(가장 높은 제품), match_score, match_level, match_reasons, match_count, matches(전체 목록)
    """
    cols = ["match_product", "match_score", "match_level", "match_reasons", "match_count", "matches"]
    if df is None or df.empty:
        return pd.DataFrame(columns=cols)
    rows = []
    for _, r in df.iterrows():
        tags = r.get(tag_col) if tag_col in df else ()
        ms = match_text(products, r.get(text_col), tags if isinstance(tags, (list, tuple)) else ()) if products else []
        if ms and pharma_col in df and not bool(r.get(pharma_col)):          # 의약품 판정과 어긋나면 확신하지 않는다
            ms = sorted((_cap_not_pharma(m) for m in ms), key=lambda m: (-m.score, m.product))
        top = ms[0] if ms else None
        rows.append({"match_product": top.product if top else None, "match_score": top.score if top else None,
                     "match_level": top.level if top else None, "match_reasons": " · ".join(top.reasons) if top else None,
                     "match_count": len(ms), "matches": ms})
    return pd.DataFrame(rows, index=df.index, columns=cols)
