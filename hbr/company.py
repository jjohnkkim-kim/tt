"""회사 설정 로직(화면과 분리): 관심 제품 목록 동기화."""
from __future__ import annotations

import pandas as pd

from .store.repo import Repo

COLUMNS = {"id": "id", "name": "제품명", "ingredient": "성분명", "product_group": "제품군", "manufacturer": "제조사",
           "insurance_code": "보험코드", "atc_code": "ATC", "keywords": "동의어(쉼표 구분)"}


def products_frame(products: list[dict]) -> pd.DataFrame:
    """저장된 제품 → 편집용 표 (동의어는 쉼표 문자열)."""
    rows = [{**{k: p.get(k) for k in COLUMNS if k != "keywords"}, "keywords": ", ".join(p.get("keywords") or [])} for p in products]
    return pd.DataFrame(rows, columns=list(COLUMNS)).rename(columns=COLUMNS)


def _clean(v):
    return None if v is None or (isinstance(v, float) and pd.isna(v)) else v


def sync_products(repo: Repo, company_id: int, records: list[dict]) -> tuple[int, list[str]]:
    """편집한 표(records)를 그 회사의 제품 목록에 반영한다.

    - id 가 있고 그 회사의 제품이면 수정(이름 변경 포함), 없으면 추가
    - 표에서 사라진 제품은 삭제 — 단, 오류가 하나라도 있으면 삭제하지 않는다
    - 항상 company_id 범위 안에서만 동작한다 (다른 회사 제품은 읽지도 쓰지도 않는다)
    반환: (저장한 개수, 오류 메시지 목록)
    """
    own = {int(p["id"]) for p in repo.list_products(company_id)}
    keep: set[int] = set()
    errors: list[str] = []
    saved = 0
    for rec in records:
        name = str(_clean(rec.get("제품명")) or "").strip()
        if not name:
            continue
        vals = dict(ingredient=_clean(rec.get("성분명")), product_group=_clean(rec.get("제품군")), manufacturer=_clean(rec.get("제조사")),
                    insurance_code=_clean(rec.get("보험코드")), atc_code=_clean(rec.get("ATC")), keywords=_clean(rec.get("동의어(쉼표 구분)")) or "")
        try:
            pid = _clean(rec.get("id"))
            if pid is not None and int(pid) in own:
                repo.update_product(company_id, int(pid), name, **vals)
                keep.add(int(pid))
            else:
                keep.add(int(repo.save_product(company_id, name, **vals)["id"]))
            saved += 1
        except ValueError as e:
            errors.append(f"{name}: {e}")
    if not errors:
        for gone in own - keep:
            repo.delete_product(company_id, gone)
    return saved, errors
