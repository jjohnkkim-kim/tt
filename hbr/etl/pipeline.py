"""ETL: 나라장터 수집 → 병원 필터 → 중복 제거 → 정제 → 저장."""
from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime

from ..store.repo import Repo
from ..utils import now_kst, today_kst
from .normalize import completeness, hospital_row, normalize_award, normalize_bid, normalize_contract

log = logging.getLogger(__name__)

DATASETS = ("bids", "awards", "contracts")
KEY = {"bids": "bid_key", "awards": "award_key", "contracts": "contract_key"}


@dataclass
class RunStats:
    job: str
    fetched: int = 0
    kept: int = 0          # 병원 필터 통과
    upserted: int = 0      # 중복 제거 후 저장
    error: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.error is None


def dedupe(rows: list[dict], key: str) -> list[dict]:
    """같은 key 중 정보가 더 많은(동률이면 나중) 행만 유지."""
    best: dict[str, dict] = {}
    for r in rows:
        cur = best.get(r[key])
        if cur is None or completeness(r) >= completeness(cur):
            best[r[key]] = r
    return list(best.values())


def run_dataset(repo: Repo, client, dataset: str, start: date, end: date) -> RunStats:
    """한 데이터셋 ETL. 실패해도 이력(pipeline_runs)을 남기고 예외는 삼키지 않고 stats.error 로 반환."""
    stats = RunStats(job=dataset)
    started = now_kst()
    try:
        competitors = repo.competitor_index()
        rows: list[dict] = []
        for raw in client.fetch(dataset, start, end):
            stats.fetched += 1
            if dataset == "bids":
                row = normalize_bid(raw)
            elif dataset == "awards":
                row = normalize_award(raw, competitors)
            else:
                row = normalize_contract(raw, competitors)
            if row:
                rows.append(row)
        stats.kept = len(rows)
        counts = Counter(r[KEY[dataset]] for r in rows) if dataset == "awards" else None
        rows = dedupe(rows, KEY[dataset])
        if counts is not None:                     # 같은 공고의 투찰업체 수(개찰 결과 행 수)
            for r in rows:
                r["bidder_count"] = counts[r[KEY[dataset]]]
        stats.upserted = save_rows(repo, dataset, rows)
    except Exception as e:                     # noqa: BLE001 — 운영 이력에 남기고 상위에서 판단
        log.exception("%s 수집 실패", dataset)
        stats.error = f"{type(e).__name__}: {e}"
    repo.log_run(dataset, "success" if stats.ok else "failed", started, now_kst(),
                 stats.fetched, stats.kept, stats.upserted, stats.error)
    return stats


def save_rows(repo: Repo, dataset: str, rows: list[dict]) -> int:
    if not rows:
        return 0
    hospitals = repo.upsert_hospitals([hospital_row(r["inst_name"]) for r in rows])
    from ..utils import normalize_name

    for r in rows:
        r["hospital_id"] = hospitals[normalize_name(r["inst_name"])]
    return repo.upsert(dataset, rows)


def run_all(repo: Repo, client, days_back: int = 3, today: date | None = None,
            datasets: tuple[str, ...] = DATASETS) -> list[RunStats]:
    from datetime import timedelta

    today = today or today_kst()
    start = today - timedelta(days=days_back)
    return [run_dataset(repo, client, ds, start, today) for ds in datasets]
