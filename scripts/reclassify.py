"""저장된 공고/낙찰/계약의 의약품 여부(is_pharma)·제품군 태그를 현재 규칙으로 다시 계산한다.

분류 규칙(hbr/collectors/hospital_filter.py)을 바꾼 뒤 한 번 실행하면 이미 저장된 데이터에도 반영된다.

  python scripts/reclassify.py --dry-run   # 바뀔 항목만 출력 (저장 안 함)
  python scripts/reclassify.py             # 변경 저장
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hbr.collectors.hospital_filter import pharma_tags   # noqa: E402
from hbr.config import get_settings                      # noqa: E402
from hbr.store.repo import get_repo                      # noqa: E402

TABLES = {"bids": "bid_key", "awards": "award_key", "contracts": "contract_key"}


def reclassify(repo, dry_run: bool = False) -> dict:
    stats = {}
    for table, key in TABLES.items():
        changed = flipped = 0
        for row in repo.rows(table, limit=100000):
            division = (row.get("raw") or {}).get("bsnsDivNm")
            ok, tags = pharma_tags(row.get("title"), division=division)
            if bool(row.get("is_pharma")) == ok and (row.get("product_tags") or []) == tags:
                continue
            changed += 1
            flipped += bool(row.get("is_pharma")) != ok
            print(f"[{table}] {'의약품' if row.get('is_pharma') else '비의약품'} → {'의약품' if ok else '비의약품'} {tags}  {str(row.get('title'))[:60]}")
            if not dry_run:
                repo.update(table, {"is_pharma": ok, "product_tags": tags}, [(key, "eq", row[key])])
        stats[table] = {"changed": changed, "pharma_flag_changed": flipped}
    return stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    s = get_settings()
    if not s.use_supabase:
        print("Supabase 미설정 — 종료")
        return 2
    print(reclassify(get_repo(s, seed_demo=False), args.dry_run))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
