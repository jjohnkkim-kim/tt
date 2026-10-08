"""텔레그램 요약 푸시 발송.

  python scripts/send_telegram.py                # 신규 의약품 공고 + 마감 임박 요약 발송
  python scripts/send_telegram.py --dry-run      # 발송하지 않고 내용만 출력
  python scripts/send_telegram.py --find-chat-id # 봇에게 메시지를 보낸 뒤 chat id 확인
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hbr.analytics.data import load_snapshot            # noqa: E402
from hbr.config import get_settings, telegram_config    # noqa: E402
from hbr.notify.telegram import TelegramError, build_digest, find_chat_ids, send_message   # noqa: E402
from hbr.store.repo import get_repo                     # noqa: E402
from hbr.utils import today_kst                         # noqa: E402


def _annotate(msg: str) -> None:
    """GitHub Actions 요약 화면(Annotations)에 보이도록 출력. 로컬에서는 일반 출력."""
    print(f"::error title=Telegram::{msg.replace(chr(10), ' ')[:900]}" if os.getenv("GITHUB_ACTIONS") else f"ERROR: {msg}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--find-chat-id", action="store_true")
    ap.add_argument("--all", action="store_true", help="의약품 외 공고도 포함")
    args = ap.parse_args(argv)
    token, chat_id = telegram_config()
    try:
        if args.find_chat_id:
            chats = find_chat_ids(token)
            if not chats:
                print("메시지가 없습니다. 텔레그램에서 봇에게 아무 메시지(예: /start)를 보낸 뒤 다시 실행하세요.")
                return 1
            for cid, name in chats:
                print(f"chat_id={cid}  ({name})")
            return 0
        s = get_settings()
        if not s.use_supabase:
            _annotate("Supabase 미설정 — 종료")
            return 2
        snap = load_snapshot(get_repo(s, seed_demo=False))
        text = build_digest(snap.bids, today_kst(), pharma_only=not args.all, app_url=s.app_base_url)
        if text is None:
            print("보낼 신규/마감 임박 공고가 없어 발송하지 않습니다.")
            return 0
        if args.dry_run:
            print(text)
            return 0
        print(f"텔레그램 {send_message(token, chat_id, text)}통 발송")
        return 0
    except TelegramError as e:
        _annotate(str(e))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
