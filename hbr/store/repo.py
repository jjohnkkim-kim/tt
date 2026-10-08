"""데이터 접근 계층: 백엔드 위에 DataFrame/도메인 헬퍼를 제공."""
from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from ..constants import ALERT_TYPES, COMPETITOR_SEEDS
from ..utils import normalize_name
from .backends import Backend, Filter, MemoryBackend, SupabaseBackend

DATE_COLS = {"bid_date", "award_date", "contract_date", "start_date", "end_date",
             "score_date", "report_date", "open_date"}
DATETIME_COLS = {"deadline"}                   # timestamptz → KST naive
UTC_COLS = {"created_at", "updated_at", "sent_at", "dispatched_at", "last_login_at"}

TABLES = ["hospitals", "competitors", "bids", "awards", "contracts", "opportunity_scores",
          "alerts", "subscriptions", "users", "email_reports", "pipeline_runs"]


def _to_kst_naive(s: pd.Series) -> pd.Series:
    out = pd.to_datetime(s, errors="coerce", utc=True, format="mixed")
    return out.dt.tz_convert("Asia/Seoul").dt.tz_localize(None)


class Repo:
    def __init__(self, backend: Backend) -> None:
        self.b = backend

    # ── 조회 ────────────────────────────────────────────────
    def rows(self, table: str, filters: list[Filter] | None = None,
             order: str | None = None, limit: int | None = None) -> list[dict]:
        return self.b.select(table, filters, order, limit)

    def df(self, table: str, filters: list[Filter] | None = None) -> pd.DataFrame:
        df = pd.DataFrame(self.b.select(table, filters))
        for c in df.columns:
            if c in DATE_COLS:
                df[c] = pd.to_datetime(df[c], errors="coerce")
            elif c in DATETIME_COLS or c in UTC_COLS:
                df[c] = _to_kst_naive(df[c])
        return df

    # ── 쓰기 ────────────────────────────────────────────────
    def upsert(self, table: str, rows: list[dict], on_conflict=None) -> int:
        return self.b.upsert(table, rows, on_conflict) if rows else 0

    def insert(self, table: str, rows: list[dict]) -> list[dict]:
        return self.b.insert(table, rows)

    def update(self, table: str, values: dict, filters: list[Filter]) -> None:
        self.b.update(table, values, filters)

    def delete(self, table: str, filters: list[Filter]) -> None:
        self.b.delete(table, filters)

    # ── 경쟁사 ──────────────────────────────────────────────
    def seed_competitors(self) -> None:
        if self.b.select("competitors", limit=1):
            return
        self.b.upsert("competitors", [
            {"name": n, "aliases": a, "is_own": own, "is_active": True}
            for n, a, own in COMPETITOR_SEEDS
        ])

    def competitor_index(self) -> list[dict]:
        return self.b.select("competitors", [("is_active", "eq", True)])

    # ── 병원 ────────────────────────────────────────────────
    def upsert_hospitals(self, items: list[dict]) -> dict[str, int]:
        """items: hospital dict (name, hospital_type, region ...). 반환: name_norm → id"""
        uniq: dict[str, dict] = {}
        for it in items:
            uniq[it["name_norm"]] = it
        self.b.upsert("hospitals", list(uniq.values()))
        found = self.b.select("hospitals", [("name_norm", "in", list(uniq))]) if len(uniq) <= 200 else [
            h for h in self.b.select("hospitals") if h["name_norm"] in uniq]
        return {h["name_norm"]: h["id"] for h in found}

    def hospital_id_by_name(self, name: str) -> int | None:
        rows = self.b.select("hospitals", [("name_norm", "eq", normalize_name(name))], limit=1)
        return rows[0]["id"] if rows else None

    # ── 사용자 / 구독 ────────────────────────────────────────
    def get_user(self, email: str) -> dict | None:
        rows = self.b.select("users", [("email", "eq", email.lower())], limit=1)
        return rows[0] if rows else None

    def ensure_user(self, email: str, name: str, role: str) -> dict:
        u = self.get_user(email)
        if u:
            return u
        return self.b.insert("users", [{"email": email.lower(), "name": name, "role": role,
                                        "is_active": True, "report_enabled": True}])[0]

    def watched_hospital_ids(self, user_id: int) -> set[int]:
        return {s["hospital_id"] for s in self.b.select("subscriptions", [("user_id", "eq", user_id)])
                if s.get("hospital_id") is not None}

    def add_watch(self, user_id: int, hospital_id: int) -> bool:
        if hospital_id in self.watched_hospital_ids(user_id):
            return False
        self.b.insert("subscriptions", [{"user_id": user_id, "hospital_id": hospital_id,
                                         "alert_types": list(ALERT_TYPES), "channel": "email"}])
        return True

    def remove_watch(self, user_id: int, hospital_id: int) -> None:
        self.b.delete("subscriptions", [("user_id", "eq", user_id), ("hospital_id", "eq", hospital_id)])

    # ── 파이프라인 실행 이력 ─────────────────────────────────
    def log_run(self, job: str, status: str, started: datetime, finished: datetime,
                fetched: int = 0, kept: int = 0, upserted: int = 0, error: str | None = None) -> None:
        self.b.insert("pipeline_runs", [{
            "job": job, "status": status, "started_at": started.isoformat(),
            "finished_at": finished.isoformat(), "fetched": fetched, "kept": kept,
            "upserted": upserted, "error": (error or "")[:2000] or None}])


def make_backend(settings) -> Backend:
    if settings.use_supabase:
        return SupabaseBackend(settings.supabase_url, settings.supabase_key)
    return MemoryBackend()


def get_repo(settings=None, seed_demo: bool = True) -> Repo:
    """설정에 맞는 Repo. Supabase 미설정이면 데모 데이터가 채워진 메모리 DB."""
    from ..config import get_settings

    settings = settings or get_settings()
    backend = make_backend(settings)
    repo = Repo(backend)
    repo.seed_competitors()
    if isinstance(backend, MemoryBackend) and seed_demo:
        from .demo_data import load_demo

        load_demo(repo)
    return repo
