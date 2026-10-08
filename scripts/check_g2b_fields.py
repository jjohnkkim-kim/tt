"""나라장터 API 실제 응답 필드 점검 — 키 연결 직후 한 번 실행해 normalize.FIELDS 와 맞는지 확인한다.

  python scripts/check_g2b_fields.py                  # 최근 2일, 3개 데이터셋 모두
  python scripts/check_g2b_fields.py --dataset bids --days 5
  python scripts/check_g2b_fields.py --save-sample samples/g2b.json   # 원본 3건씩 저장(커밋 금지)

종료 코드: 0 정상 / 1 필수 필드 미매칭·호출 실패·빈 응답 / 2 SERVICE_KEY 미설정
출력에 SERVICE_KEY 는 절대 포함되지 않는다.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hbr.collectors.field_check import FieldReport, analyze, collect_sample, render   # noqa: E402
from hbr.collectors.g2b import OPERATIONS, G2BClient, G2BError                          # noqa: E402
from hbr.config import get_settings                                                      # noqa: E402
from hbr.constants import COMPETITOR_SEEDS                                               # noqa: E402
from hbr.utils import today_kst                                                          # noqa: E402


def main(argv=None, client=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", choices=[*OPERATIONS, "all"], default="all")
    ap.add_argument("--days", type=int, default=2, help="오늘 기준 N일 전부터 (기본 2)")
    ap.add_argument("--max-rows", type=int, default=300, help="필드 분석에 쓸 표본 건수")
    ap.add_argument("--scan-limit", type=int, default=3000, help="병원 표본을 찾기 위해 최대 스캔할 건수")
    ap.add_argument("--save-sample", help="원본 응답 3건씩 JSON 저장 경로 (비밀 아님, 그래도 커밋 금지)")
    args = ap.parse_args(argv)

    s = get_settings()
    if client is None:
        try:
            client = G2BClient(s.service_key, s.g2b_base_url, rows_per_page=100)
        except G2BError as e:
            print(f"✗ {e}", file=sys.stderr)
            return 2
    competitors = [{"id": i + 1, "name": n, "aliases": a, "is_own": own} for i, (n, a, own) in enumerate(COMPETITOR_SEEDS)]
    end = today_kst()
    start = end - timedelta(days=args.days)
    datasets = list(OPERATIONS) if args.dataset == "all" else [args.dataset]
    print(f"엔드포인트: {s.g2b_base_url}  기간: {start} ~ {end}")
    reports: list[FieldReport] = []
    saved: dict[str, list] = {}
    for ds in datasets:
        rep = FieldReport(dataset=ds, operation=OPERATIONS[ds][0])
        try:
            probe = client.probe(ds, start, end)
            rep.params, rep.total = probe["params"], probe["total"]
            rows, hosp, scanned = collect_sample(client, ds, start, end, args.max_rows, args.scan_limit)
            full = analyze(ds, rows, hosp, competitors, scanned)
            full.operation, full.params, full.total = rep.operation, rep.params, rep.total
            rep = full
            saved[ds] = (hosp or rows)[:3]
        except G2BError as e:
            rep.error = str(e)
        reports.append(rep)
        print(render(rep))
    if args.save_sample:
        out = Path(args.save_sample)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n원본 표본 저장: {out}  (커밋하지 마세요)")
    bad = [r.dataset for r in reports if not r.ok]
    print("\n요약: " + ("모든 데이터셋 정상" if not bad else f"점검 필요 → {', '.join(bad)}"))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
