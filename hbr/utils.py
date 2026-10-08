"""날짜·금액·문자열 공통 유틸."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def today_kst() -> date:
    return datetime.now(KST).date()


def now_kst() -> datetime:
    return datetime.now(KST)


def parse_dt(value) -> datetime | None:
    """'2026-10-08', '20261008', '202610081127', '2026-10-08 11:27:00' 등을 파싱."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    s = str(value).strip()
    if not s or s.lower() in {"nan", "none", "null"}:
        return None
    digits = re.sub(r"\D", "", s)
    try:
        if len(digits) >= 14:
            return datetime.strptime(digits[:14], "%Y%m%d%H%M%S")
        if len(digits) >= 12:
            return datetime.strptime(digits[:12], "%Y%m%d%H%M")
        if len(digits) >= 8:
            return datetime.strptime(digits[:8], "%Y%m%d")
    except ValueError:
        return None
    return None


def parse_date(value) -> date | None:
    dt = parse_dt(value)
    return dt.date() if dt else None


def to_amount(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = re.sub(r"[^\d.\-]", "", str(value))
    if s in {"", "-", "."}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def fmt_won(amount) -> str:
    """금액을 '5.2억원' / '3,500만원' 형태로."""
    if amount is None or amount != amount:
        return "-"
    a = float(amount)
    if abs(a) >= 1e8:
        return f"{a / 1e8:,.1f}억원"
    if abs(a) >= 1e4:
        return f"{a / 1e4:,.0f}만원"
    return f"{a:,.0f}원"


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    last = [31, 29 if year % 4 == 0 and (year % 100 or year % 400 == 0) else 28,
            31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
    return date(year, month, min(d.day, last))


def date_windows(start: date, end: date, days: int):
    """[start, end] 를 days 일 단위 구간으로 분할 (API 조회기간 제한 대응)."""
    cur = start
    while cur <= end:
        nxt = min(cur + timedelta(days=days - 1), end)
        yield cur, nxt
        cur = nxt + timedelta(days=1)


_CORP_NOISE = re.compile(r"\(주\)|㈜|주식회사|\(재\)|재단법인|\(학\)|학교법인|\(의\)|의료법인|\s+")


def normalize_name(name: str | None) -> str:
    """상호/기관명 비교용 정규화 (공백·법인 표기 제거)."""
    if not name:
        return ""
    return _CORP_NOISE.sub("", str(name)).strip().lower()
