"""텔레그램 봇 푸시: 신규 의약품 공고 + 마감 임박 공고를 하루 한 통으로 요약해 발송."""
from __future__ import annotations

from datetime import date
from html import escape

import pandas as pd
import requests

API = "https://api.telegram.org"
MAX_LEN = 4000            # 텔레그램 메시지 한도 4096자
MAX_ITEMS = 15            # 섹션당 표시 건수 (나머지는 '외 N건')
DEADLINE_DAYS = 3


class TelegramError(RuntimeError):
    pass


def _won(v) -> str:
    if v is None or pd.isna(v) or float(v) <= 0:
        return ""
    v = float(v)
    return f" · {v / 1e8:,.2f}억" if v >= 1e8 else f" · {v / 1e4:,.0f}만원"


def _line(r: pd.Series, today: date) -> str:
    title = escape(str(r["title"]))
    url = r.get("url")
    head = f'<a href="{escape(str(url), quote=True)}">{title}</a>' if isinstance(url, str) and url else title
    tags = r.get("product_tags")
    tag = f" 〔{escape(', '.join(tags))}〕" if isinstance(tags, (list, tuple)) and tags else ""
    dl = r.get("deadline")
    when = ""
    if dl is not None and not pd.isna(dl):
        d = (dl.normalize() - pd.Timestamp(today)).days
        when = f" · 마감 {dl:%m/%d} (D-{d})" if d >= 0 else f" · 마감 {dl:%m/%d}"
    return f"• {head}{tag}\n   {escape(str(r.get('hospital') or '-'))}{_won(r.get('budget'))}{when}"


def _section(title: str, df: pd.DataFrame, today: date) -> str:
    if df.empty:
        return ""
    lines = [_line(r, today) for _, r in df.head(MAX_ITEMS).iterrows()]
    more = f"\n… 외 {len(df) - MAX_ITEMS}건" if len(df) > MAX_ITEMS else ""
    return f"<b>{title} {len(df)}건</b>\n" + "\n".join(lines) + more


def build_digest(bids: pd.DataFrame, today: date, new_days: int = 1, pharma_only: bool = True) -> str | None:
    """보낼 내용이 없으면 None."""
    if bids is None or bids.empty:
        return None
    df = bids
    if pharma_only and "is_pharma" in df:
        df = df[df["is_pharma"].fillna(False).astype(bool)]
    t = pd.Timestamp(today)
    new = df[df["bid_date"] >= t - pd.Timedelta(days=new_days)].sort_values("bid_date", ascending=False)
    soon = df[(df["deadline"] >= t) & (df["deadline"] < t + pd.Timedelta(days=DEADLINE_DAYS + 1))].sort_values("deadline")
    new = new[~new["bid_ntce_no"].isin(soon["bid_ntce_no"])] if not soon.empty else new
    parts = [_section("🆕 신규 의약품 공고" if pharma_only else "🆕 신규 공고", new, today),
             _section(f"⏰ 마감 임박({DEADLINE_DAYS}일 이내)", soon, today)]
    parts = [p for p in parts if p]
    if not parts:
        return None
    return f"📡 <b>Hospital Bid Radar</b> · {today:%Y-%m-%d}\n\n" + "\n\n".join(parts)


def split_message(text: str, limit: int = MAX_LEN) -> list[str]:
    """줄 단위로 한도 이하로 분할."""
    chunks, cur = [], ""
    for line in text.split("\n"):
        if cur and len(cur) + len(line) + 1 > limit:
            chunks.append(cur)
            cur = ""
        cur = f"{cur}\n{line}" if cur else line
    if cur:
        chunks.append(cur)
    return chunks


def send_message(token: str, chat_id: str, text: str, session: requests.Session | None = None) -> int:
    if not token or not chat_id:
        raise TelegramError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 가 설정되지 않았습니다 (.env 확인)")
    http = session or requests.Session()
    sent = 0
    for chunk in split_message(text):
        r = http.post(f"{API}/bot{token}/sendMessage", timeout=30, json={
            "chat_id": chat_id, "text": chunk, "parse_mode": "HTML", "disable_web_page_preview": True})
        body = r.json() if r.content else {}
        if r.status_code != 200 or not body.get("ok"):
            # 토큰이 URL 에 들어가므로 예외 메시지에는 응답 설명만 담는다
            raise TelegramError(f"텔레그램 발송 실패 (HTTP {r.status_code}): {body.get('description', r.text[:120])}")
        sent += 1
    return sent


def find_chat_ids(token: str, session: requests.Session | None = None) -> list[tuple[str, str]]:
    """봇에게 메시지를 보낸 채팅 목록 [(chat_id, 이름)] — 최초 설정 시 chat id 확인용."""
    r = (session or requests).get(f"{API}/bot{token}/getUpdates", timeout=30)
    body = r.json() if r.content else {}
    if r.status_code != 200 or not body.get("ok"):
        raise TelegramError(f"getUpdates 실패 (HTTP {r.status_code}): {body.get('description', '')}")
    seen: dict[str, str] = {}
    for u in body.get("result", []):
        chat = (u.get("message") or u.get("channel_post") or {}).get("chat") or {}
        if "id" in chat:
            seen[str(chat["id"])] = chat.get("title") or chat.get("username") or chat.get("first_name") or ""
    return list(seen.items())
