"""저장소 백엔드: Supabase(운영) / Memory(데모·테스트). 동일 인터페이스."""
from __future__ import annotations

import copy
import math
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol

Filter = tuple[str, str, Any]   # (column, op, value)  op: eq|neq|in|gte|lte|gt|lt|isnull

# 테이블별 upsert 충돌키 (SQL 의 UNIQUE 와 일치해야 함)
UNIQUE_KEYS: dict[str, tuple[str, ...]] = {
    "hospitals": ("name_norm",),
    "competitors": ("name",),
    "bids": ("bid_key",),
    "awards": ("award_key",),
    "contracts": ("contract_key",),
    "users": ("email",),
    "opportunity_scores": ("hospital_id", "score_date"),
    "alerts": ("dedup_key",),
    "email_reports": ("report_date", "recipient"),
    "company_products": ("company_id", "name"),
    "alert_rules": ("user_id",),
}


def clean_value(v: Any) -> Any:
    """JSON 직렬화 가능한 값으로 변환."""
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    if isinstance(v, dict):
        return {k: clean_value(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [clean_value(x) for x in v]
    if hasattr(v, "item") and not isinstance(v, (str, bytes)):   # numpy 스칼라
        try:
            return clean_value(v.item())
        except Exception:
            return v
    return v


def clean_row(row: dict) -> dict:
    return {k: clean_value(v) for k, v in row.items()}


class Backend(Protocol):
    def select(self, table: str, filters: list[Filter] | None = None,
               order: str | None = None, limit: int | None = None) -> list[dict]: ...
    def insert(self, table: str, rows: list[dict]) -> list[dict]: ...
    def upsert(self, table: str, rows: list[dict], on_conflict: tuple[str, ...] | None = None) -> int: ...
    def update(self, table: str, values: dict, filters: list[Filter]) -> None: ...
    def delete(self, table: str, filters: list[Filter]) -> None: ...


# ─────────────────────────────────────────────────────────────
class MemoryBackend:
    """인메모리 백엔드. Supabase 없이 데모/테스트를 돌리기 위한 용도."""

    def __init__(self) -> None:
        self.tables: dict[str, list[dict]] = {}
        self._seq: dict[str, int] = {}

    # --- helpers
    def _rows(self, table: str) -> list[dict]:
        return self.tables.setdefault(table, [])

    @staticmethod
    def _match(row: dict, f: Filter) -> bool:
        col, op, val = f
        cur = row.get(col)
        if op == "eq":
            return cur == val
        if op == "neq":
            return cur != val
        if op == "in":
            return cur in set(val)
        if op == "isnull":
            return (cur is None) == bool(val)
        if cur is None:
            return False
        try:
            if op == "gte":
                return cur >= val
            if op == "lte":
                return cur <= val
            if op == "gt":
                return cur > val
            if op == "lt":
                return cur < val
        except TypeError:
            return False
        raise ValueError(f"unknown op {op}")

    def _filtered(self, table: str, filters: list[Filter] | None) -> list[dict]:
        rows = self._rows(table)
        for f in filters or []:
            rows = [r for r in rows if self._match(r, f)]
        return rows

    def _apply_defaults(self, table: str, row: dict) -> dict:
        row = clean_row(row)
        if "id" not in row or row["id"] is None:
            self._seq[table] = self._seq.get(table, 0) + 1
            row["id"] = self._seq[table]
        else:
            self._seq[table] = max(self._seq.get(table, 0), int(row["id"]))
        row.setdefault("created_at", datetime.utcnow().isoformat())
        return row

    # --- API
    def select(self, table, filters=None, order=None, limit=None):
        rows = self._filtered(table, filters)
        if order:
            desc = order.startswith("-")
            key = order.lstrip("-")
            rows = sorted(rows, key=lambda r: (r.get(key) is None, r.get(key)), reverse=desc)
        if limit:
            rows = rows[:limit]
        return copy.deepcopy(rows)

    def insert(self, table, rows):
        out = []
        for r in rows:
            uk = UNIQUE_KEYS.get(table)
            row = self._apply_defaults(table, r)
            if uk and any(all(x.get(k) == row.get(k) for k in uk) for x in self._rows(table)):
                raise ValueError(f"unique violation on {table}{uk}")
            self._rows(table).append(row)
            out.append(copy.deepcopy(row))
        return out

    def upsert(self, table, rows, on_conflict=None):
        uk = on_conflict or UNIQUE_KEYS.get(table)
        if not uk:
            return len(self.insert(table, rows))
        existing = {tuple(r.get(k) for k in uk): r for r in self._rows(table)}
        for r in rows:
            r = clean_row(r)
            key = tuple(r.get(k) for k in uk)
            if key in existing:
                existing[key].update(r)
            else:
                row = self._apply_defaults(table, r)
                self._rows(table).append(row)
                existing[key] = row
        return len(rows)

    def update(self, table, values, filters):
        for r in self._filtered(table, filters):
            r.update(clean_row(values))

    def delete(self, table, filters):
        doomed = {id(r) for r in self._filtered(table, filters)}
        self.tables[table] = [r for r in self._rows(table) if id(r) not in doomed]


# ─────────────────────────────────────────────────────────────
class SupabaseBackend:
    """supabase-py(PostgREST) 백엔드. 서버 전용 Secret key 로만 생성한다."""

    PAGE = 1000          # PostgREST 기본 최대 행 수
    UPSERT_CHUNK = 500

    def __init__(self, url: str, key: str) -> None:
        from supabase import create_client

        self.client = create_client(url, key)

    def _apply(self, q, filters: list[Filter] | None):
        for col, op, val in filters or []:
            if op == "eq":
                q = q.eq(col, val)
            elif op == "neq":
                q = q.neq(col, val)
            elif op == "in":
                q = q.in_(col, list(val))
            elif op == "gte":
                q = q.gte(col, clean_value(val))
            elif op == "lte":
                q = q.lte(col, clean_value(val))
            elif op == "gt":
                q = q.gt(col, clean_value(val))
            elif op == "lt":
                q = q.lt(col, clean_value(val))
            elif op == "isnull":
                q = q.is_(col, "null") if val else q.not_.is_(col, "null")
            else:
                raise ValueError(f"unknown op {op}")
        return q

    def select(self, table, filters=None, order=None, limit=None):
        out: list[dict] = []
        offset = 0
        order_col, desc = (order.lstrip("-"), order.startswith("-")) if order else ("id", False)
        while True:
            page = self.PAGE if limit is None else min(self.PAGE, limit - len(out))
            if page <= 0:
                break
            q = self._apply(self.client.table(table).select("*"), filters)
            q = q.order(order_col, desc=desc).range(offset, offset + page - 1)
            data = q.execute().data or []
            out.extend(data)
            if len(data) < page:
                break
            offset += page
        return out

    def insert(self, table, rows):
        if not rows:
            return []
        return self.client.table(table).insert([clean_row(r) for r in rows]).execute().data or []

    def upsert(self, table, rows, on_conflict=None):
        uk = on_conflict or UNIQUE_KEYS.get(table)
        n = 0
        for i in range(0, len(rows), self.UPSERT_CHUNK):
            chunk = [clean_row(r) for r in rows[i:i + self.UPSERT_CHUNK]]
            q = self.client.table(table).upsert(chunk, on_conflict=",".join(uk) if uk else None)
            q.execute()
            n += len(chunk)
        return n

    def update(self, table, values, filters):
        self._apply(self.client.table(table).update(clean_row(values)), filters).execute()

    def delete(self, table, filters):
        self._apply(self.client.table(table).delete(), filters).execute()
