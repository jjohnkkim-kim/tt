"""수집·분석 파이프라인 CLI.

  python scripts/run_pipeline.py --job all            # bids → awards → contracts → scores → alerts
  python scripts/run_pipeline.py --job bids --days 1  # 증분 수집
  python scripts/run_pipeline.py --job bids --start 2025-01-01 --end 2025-12-31   # 백필
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hbr.analytics.alerts import generate_alerts          # noqa: E402
from hbr.analytics.scoring import ensure_scores           # noqa: E402
from hbr.collectors.g2b import G2BClient                  # noqa: E402
from hbr.config import bids_only, get_settings                       # noqa: E402
from hbr.etl.pipeline import DATASETS, run_dataset        # noqa: E402
from hbr.store.repo import get_repo                       # noqa: E402
from hbr.utils import today_kst                           # noqa: E402


def _annotate(msg: str, level: str = "error") -> None:
    """GitHub Actions 요약 화면(Annotations)에 보이도록 출력. 로컬에서는 일반 출력."""
    if os.getenv("GITHUB_ACTIONS"):
        print(f"::{level} title=Pipeline::{msg.replace(chr(10), ' ')[:900]}")
    else:
        print(f"[{level}] {msg}")


def main(argv=None) -> int:
    try:
        return _run(argv)
    except Exception as e:      # noqa: BLE001 — 원인을 요약 화면에 남기고 실패로 종료
        _annotate(f"{type(e).__name__}: {e}")
        raise


def _run(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", default="all", choices=[*DATASETS, "scores", "alerts", "collect", "all"])
    ap.add_argument("--days", type=int, default=3, help="오늘 기준 N일 전부터 수집")
    ap.add_argument("--start", type=date.fromisoformat)
    ap.add_argument("--end", type=date.fromisoformat)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    s = get_settings()
    if os.getenv("GITHUB_ACTIONS"):      # 값은 출력하지 않고 설정 여부만
        cfg = {"SERVICE_KEY": s.service_key, "SUPABASE_URL": s.supabase_url, "SUPABASE_SECRET_KEY": s.supabase_key}
        _annotate("설정 확인: " + ", ".join(f"{k}={'있음' if v else '비어있음'}" for k, v in cfg.items()), "notice")
        raw = os.getenv("SUPABASE_URL", "")      # 값 자체는 출력하지 않고 형태만
        bare = raw.strip().strip("\"'")
        shape = {"https로시작": bare.lower().startswith("https://"), "앞뒤공백/줄바꿈": raw != raw.strip(),
                 "따옴표": raw.strip() != bare, "supabase.co포함": "supabase.co" in raw,
                 "경로포함": bare.rstrip("/").count("/") > 2}
        _annotate("SUPABASE_URL 형태: " + ", ".join(f"{k}={v}" for k, v in shape.items()), "notice")
    if not s.use_supabase:
        _annotate("Supabase 가 설정되지 않아 저장되지 않는 메모리 DB 로 실행됩니다 (SUPABASE_URL / SUPABASE_SECRET_KEY 확인).")
        return 2
    repo = get_repo(s, seed_demo=False)
    today = today_kst()
    end = args.end or today
    start = args.start or (end - timedelta(days=args.days))
    failed = False

    if args.job in (*DATASETS, "collect", "all"):
        client = G2BClient(s.service_key, s.g2b_base_url)
        targets = ("bids",) if bids_only() else DATASETS
        for ds in (targets if args.job in ("collect", "all") else (args.job,)):
            st = run_dataset(repo, client, ds, start, end)
            print(f"[{ds}] fetched={st.fetched} hospital={st.kept} saved={st.upserted} {'OK' if st.ok else 'FAIL ' + str(st.error)}")
            if not st.ok:
                _annotate(f"{ds} 수집 실패: {st.error}")
            failed |= not st.ok
    if args.job in ("scores", "all"):
        n = len(ensure_scores(repo, today))
        print(f"[scores] {n}개 병원 점수 저장")
    if args.job in ("alerts", "all"):
        print(f"[alerts] 신규 알림 {len(generate_alerts(repo, today))}건")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
