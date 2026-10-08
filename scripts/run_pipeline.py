"""수집·분석 파이프라인 CLI.

  python scripts/run_pipeline.py --job all            # bids → awards → contracts → scores → alerts
  python scripts/run_pipeline.py --job bids --days 1  # 증분 수집
  python scripts/run_pipeline.py --job bids --start 2025-01-01 --end 2025-12-31   # 백필
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hbr.analytics.alerts import generate_alerts          # noqa: E402
from hbr.analytics.scoring import ensure_scores           # noqa: E402
from hbr.collectors.g2b import G2BClient                  # noqa: E402
from hbr.config import get_settings                       # noqa: E402
from hbr.etl.pipeline import DATASETS, run_dataset        # noqa: E402
from hbr.store.repo import get_repo                       # noqa: E402
from hbr.utils import today_kst                           # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", default="all", choices=[*DATASETS, "scores", "alerts", "collect", "all"])
    ap.add_argument("--days", type=int, default=3, help="오늘 기준 N일 전부터 수집")
    ap.add_argument("--start", type=date.fromisoformat)
    ap.add_argument("--end", type=date.fromisoformat)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    s = get_settings()
    if not s.use_supabase:
        print("⚠ Supabase 가 설정되지 않아 저장되지 않는 메모리 DB 로 실행됩니다 (SUPABASE_URL / SUPABASE_SECRET_KEY 확인).")
        return 2
    repo = get_repo(s, seed_demo=False)
    today = today_kst()
    end = args.end or today
    start = args.start or (end - timedelta(days=args.days))
    failed = False

    if args.job in (*DATASETS, "collect", "all"):
        client = G2BClient(s.service_key, s.g2b_base_url)
        for ds in (DATASETS if args.job in ("collect", "all") else (args.job,)):
            st = run_dataset(repo, client, ds, start, end)
            print(f"[{ds}] fetched={st.fetched} hospital={st.kept} saved={st.upserted} {'OK' if st.ok else 'FAIL ' + str(st.error)}")
            failed |= not st.ok
    if args.job in ("scores", "all"):
        n = len(ensure_scores(repo, today))
        print(f"[scores] {n}개 병원 점수 저장")
    if args.job in ("alerts", "all"):
        print(f"[alerts] 신규 알림 {len(generate_alerts(repo, today))}건")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
