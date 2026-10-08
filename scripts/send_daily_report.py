"""Daily Report 발송.  --wait-until 08:00 : 그 시각(KST) 전이면 대기 후 발송 (Actions 지연 대비 조기 기동용)."""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, time as dtime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hbr.config import get_settings          # noqa: E402
from hbr.reports.mailer import send_daily_reports   # noqa: E402
from hbr.store.repo import get_repo          # noqa: E402
from hbr.utils import now_kst                # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait-until", help="HH:MM (KST). 이 시각까지 최대 40분 대기")
    ap.add_argument("--no-ai", action="store_true", help="AI 브리핑 생략")
    args = ap.parse_args(argv)

    s = get_settings()
    if not s.use_supabase:
        print("Supabase 미설정 — 종료")
        return 2
    if args.wait_until:
        h, m = map(int, args.wait_until.split(":"))
        target = datetime.combine(now_kst().date(), dtime(h, m), tzinfo=now_kst().tzinfo)
        wait = (target - now_kst()).total_seconds()
        if 0 < wait <= 40 * 60:
            print(f"{args.wait_until} 까지 {wait:.0f}초 대기")
            time.sleep(wait)
    stats = send_daily_reports(get_repo(s, seed_demo=False), s, briefing=not args.no_ai)
    print(stats)
    return 1 if stats["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
