"""미발송 알림을 구독자에게 이메일로 발송 (사용자별 1통 요약). 30분 주기 실행 가정."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hbr.alerts_dispatch import dispatch   # noqa: E402
from hbr.config import get_settings        # noqa: E402
from hbr.store.repo import get_repo        # noqa: E402

if __name__ == "__main__":
    s = get_settings()
    if not s.use_supabase:
        print("Supabase 미설정 — 종료")
        raise SystemExit(2)
    print(dispatch(get_repo(s, seed_demo=False), s))
