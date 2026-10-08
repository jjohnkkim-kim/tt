"""알림 생성(이벤트 감지) + 사용자별 대상 선정. 중복은 dedup_key 로 방지."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from ..constants import ALERT_TYPES, EXPIRY_MILESTONES
from ..store.repo import Repo
from ..utils import fmt_won, today_kst
from .data import load_snapshot, open_bids, pharma_only


def generate_alerts(repo: Repo, today: date | None = None, lookback_days: int = 3) -> list[dict]:
    """이벤트를 감지해 alerts 에 upsert. 반환: 이번에 새로 만든 알림."""
    today = today or today_kst()
    snap = load_snapshot(repo)
    t = pd.Timestamp(today)
    cand: list[dict] = []

    # 1) 신규 입찰 (최근 N일 공고, 마감 전)
    bids = open_bids(pharma_only(snap.bids), today)
    if not bids.empty:
        for b in bids[bids["bid_date"] >= t - pd.Timedelta(days=lookback_days)].itertuples():
            dday = (b.deadline.date() - today).days if pd.notna(b.deadline) else None
            tag = f" · {'/'.join(b.product_tags)}" if isinstance(b.product_tags, list) and b.product_tags else ""
            cand.append(_alert("NEW_BID", b.hospital_id, f"NEW_BID:{b.bid_key}",
                               f"{b.hospital} — {b.title}",
                               f"예산 {fmt_won(b.budget)}" + (f" · 마감 D-{dday}" if dday is not None else "") + tag,
                               "high" if dday is not None and dday <= 7 else "normal"))

    # 2) 계약만료 마일스톤 (D-90/60/30/7 도달 시 1회)
    con = pharma_only(snap.contracts)
    if not con.empty:
        con = con[con["end_date"].notna()]
        days = (con["end_date"] - t).dt.days
        for row, d in zip(con.itertuples(), days):
            # 가장 작은 마일스톤 중 d 이하인 것 — 예: d=75 → 90 도달
            hit = [m for m in EXPIRY_MILESTONES if d <= m and d >= 0]
            if not hit:
                continue
            m = min(hit)
            cand.append(_alert("CONTRACT_EXPIRY", row.hospital_id, f"EXP:{row.contract_key}:{m}",
                               f"{row.hospital} — 계약종료 D-{d}",
                               f"{row.title} · {row.vendor_name or '-'} · {fmt_won(row.contract_amount)} "
                               f"· 종료 {row.end_date.date()}" + (" (추정)" if row.end_date_estimated else ""),
                               "high" if m <= 30 else "normal"))

    # 3) 경쟁사 수주 (최근 N일; 받는 사람 회사의 수주는 recipients_for 에서 제외)
    aw = pharma_only(snap.awards)
    if not aw.empty:
        aw = aw[aw["award_date"] >= t - pd.Timedelta(days=lookback_days + 4)]      # 자사 여부는 받는 사람의 회사 기준이라 발송 때 거른다
        for a in aw.itertuples():
            cand.append(_alert("COMPETITOR_AWARD", a.hospital_id, f"AWD:{a.award_key}",
                               f"{a.competitor if a.competitor != '기타' else a.winner_name} — {a.hospital} 수주",
                               f"{a.title} · 낙찰금액 {fmt_won(a.award_amount)}", "normal"))

    existing = {r["dedup_key"] for r in repo.rows("alerts")}
    fresh = [c for c in cand if c["dedup_key"] not in existing]
    repo.upsert("alerts", fresh)
    return fresh


def _alert(kind: str, hospital_id, key: str, title: str, message: str, severity: str) -> dict:
    return {"alert_type": kind, "hospital_id": None if pd.isna(hospital_id) else int(hospital_id),
            "dedup_key": key, "title": title, "message": message, "severity": severity,
            "delivered_to": []}


def recipients_for(alert: dict, users: list[dict], subs: list[dict],
                   own_aliases_by_company: dict | None = None) -> list[dict]:
    """알림 대상: 활성 사용자 중 (해당 병원 구독 또는 전체 구독) 이고 유형을 켠 사람.
    경쟁사 수주 알림은 받는 사람 회사의 자사(표기명)가 낙찰받은 건이면 보내지 않는다."""
    from ..collectors.competitors import matches_any_alias

    winner = str(alert.get("title") or "").split(" — ")[0]
    by_user: dict[int, list[dict]] = {}
    for s in subs:
        by_user.setdefault(s["user_id"], []).append(s)
    out = []
    for u in users:
        if not u.get("is_active", True):
            continue
        if alert["alert_type"] == "COMPETITOR_AWARD" and matches_any_alias(
                winner, (own_aliases_by_company or {}).get(u.get("company_id"), [])):
            continue
        for s in by_user.get(u["id"], []):
            types = s.get("alert_types") or list(ALERT_TYPES)
            if alert["alert_type"] in types and s.get("hospital_id") in (None, alert.get("hospital_id")):
                out.append(u)
                break
    return out
