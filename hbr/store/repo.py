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
          "alerts", "subscriptions", "users", "email_reports", "pipeline_runs", "companies", "company_products"]


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

    # ── 회사(멀티테넌트) / 관심 제품 ─────────────────────────
    # 회사 번호는 항상 '로그인한 사용자의 소속'에서만 가져와 넘긴다. 화면 입력값을 그대로 쓰지 않는다.
    def get_company(self, company_id: int | None) -> dict | None:
        if not company_id:
            return None
        rows = self.b.select("companies", [("id", "eq", int(company_id))], limit=1)
        return rows[0] if rows else None

    def list_companies(self) -> list[dict]:
        return self.b.select("companies", order="name")

    def create_company(self, name: str, company_type: str = "제약사", own_aliases: list[str] | None = None) -> dict:
        name = (name or "").strip()
        if not name:
            raise ValueError("회사명을 입력해 주세요.")
        if any(c["name"].strip().lower() == name.lower() for c in self.list_companies()):
            raise ValueError("이미 등록된 회사명입니다.")
        aliases = clean_list(own_aliases or []) or [name]
        return self.b.insert("companies", [{"name": name, "company_type": company_type, "own_aliases": aliases}])[0]

    def update_company(self, company_id: int, name: str, company_type: str, own_aliases: list[str]) -> None:
        name = (name or "").strip()
        if not name:
            raise ValueError("회사명을 입력해 주세요.")
        if any(c["id"] != company_id and c["name"].strip().lower() == name.lower() for c in self.list_companies()):
            raise ValueError("이미 등록된 회사명입니다.")
        self.b.update("companies", {"name": name, "company_type": company_type, "own_aliases": clean_list(own_aliases) or [name]},
                      [("id", "eq", int(company_id))])

    def assign_company(self, user_id: int, company_id: int | None) -> None:
        self.b.update("users", {"company_id": int(company_id) if company_id else None}, [("id", "eq", int(user_id))])

    def own_aliases(self, company_id: int | None) -> list[str]:
        c = self.get_company(company_id)
        if not c:
            return []
        return clean_list([c["name"], *(c.get("own_aliases") or [])])

    def list_products(self, company_id: int | None) -> list[dict]:
        if not company_id:
            return []
        return self.b.select("company_products", [("company_id", "eq", int(company_id))], order="name")

    def save_product(self, company_id: int, name: str, **fields) -> dict:
        """제품 추가/수정(같은 회사의 같은 제품명이면 수정). 다른 회사 데이터에는 닿지 않는다."""
        if not company_id:
            raise ValueError("소속 회사가 없습니다.")
        name = (name or "").strip()
        if not name:
            raise ValueError("제품명을 입력해 주세요.")
        row = {"company_id": int(company_id), "name": name}
        for k in ("ingredient", "product_group", "manufacturer", "insurance_code", "atc_code"):
            v = (fields.get(k) or "").strip() if isinstance(fields.get(k), str) else fields.get(k)
            row[k] = v or None
        row["keywords"] = clean_list(fields.get("keywords") or [])
        self.b.upsert("company_products", [row], ("company_id", "name"))
        return next(p for p in self.list_products(company_id) if p["name"] == name)

    def update_product(self, company_id: int, product_id: int, name: str, **fields) -> None:
        """제품 수정(이름 변경 포함). 같은 회사의 행만 바뀐다."""
        name = (name or "").strip()
        if not company_id or not name:
            raise ValueError("제품명을 입력해 주세요.")
        if any(p["id"] != product_id and p["name"].strip().lower() == name.lower() for p in self.list_products(company_id)):
            raise ValueError(f"이미 같은 이름의 제품이 있습니다: {name}")
        vals = {"name": name, "keywords": clean_list(fields.get("keywords") or [])}
        for k in ("ingredient", "product_group", "manufacturer", "insurance_code", "atc_code"):
            v = fields.get(k)
            vals[k] = (v.strip() if isinstance(v, str) else v) or None
        self.b.update("company_products", vals, [("company_id", "eq", int(company_id)), ("id", "eq", int(product_id))])

    def delete_product(self, company_id: int, product_id: int) -> None:
        self.b.delete("company_products", [("company_id", "eq", int(company_id)), ("id", "eq", int(product_id))])


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


def clean_list(values) -> list[str]:
    """쉼표 문자열 또는 목록을 공백 제거·중복 제거한 목록으로."""
    if isinstance(values, str):
        values = values.replace("\n", ",").split(",")
    out: list[str] = []
    for v in values or []:
        v = str(v).strip()
        if v and v.lower() not in {x.lower() for x in out}:
            out.append(v)
    return out
