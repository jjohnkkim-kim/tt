"""알림 생성(이벤트 감지) + 사용자별 대상 선정. 중복은 dedup_key 로 방지."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from ..constants import ALERT_TYPES, DEADLINE_DAYS, EXPIRY_MILESTONES, LEGACY_ALERT_TYPES
from ..store.repo import Repo
from ..utils import fmt_won, today_kst
from .data import load_snapshot, open_bids, pharma_only
from .lifecycle import build_lifecycle


def generate_alerts(repo: Repo, today: date | None = None, lookback_days: int = 3) -> list[dict]:
    """이벤트를 감지해 alerts 에 upsert. 반환: 이번에 새로 만든 알림.

    이벤트는 모든 회사가 같이 쓰는 공통 데이터다. '누구에게 보일지'는 사용자 알림 조건(alert_rules)이 정한다.
    각 알림의 payload 에는 조건 판단에 필요한 정보(제목·낙찰업체·마감 D-day 등)를 담는다.
    """
    today = today or today_kst()
    snap = load_snapshot(repo)
    lc = build_lifecycle(snap, today)
    t = pd.Timestamp(today)
    existing = {r["dedup_key"] for r in repo.rows("alerts")}
    cand: list[dict] = []

    # 1) 신규 입찰 / 재공고 (최근 N일 공고, 마감 전)
    bids = open_bids(pharma_only(snap.bids), today)
    if not bids.empty:
        for idx, b in bids[bids["bid_date"] >= t - pd.Timedelta(days=lookback_days)].iterrows():
            dday = (b["deadline"].date() - today).days if pd.notna(b["deadline"]) else None
            tags = list(b["product_tags"]) if isinstance(b.get("product_tags"), (list, tuple)) else []
            base = {"title": b["title"], "bid_ntce_no": b["bid_ntce_no"], "tags": tags,
                    "deadline": b["deadline"].isoformat() if pd.notna(b["deadline"]) else None}
            tagtxt = f" · {'/'.join(tags)}" if tags else ""
            rebid = bool(lc.loc[idx, "is_rebid"]) if idx in lc.index else False
            if rebid and f"NEW_BID:{b['bid_key']}" not in existing:        # 예전에 신규 입찰로 이미 알린 공고는 재공고로 또 알리지 않는다
                prev = lc.loc[idx]
                note = f" · ↩ 이전 {prev['prev_status']} {pd.Timestamp(prev['prev_date']):%m/%d}(추정 연결)" if pd.notna(prev.get("prev_ntce_no")) else ""
                cand.append(_alert("REBID", b["hospital_id"], f"RB:{b['bid_key']}", f"{b['hospital']} — {b['title']}",
                                   f"재공고 · 예산 {fmt_won(b['budget'])}" + (f" · 마감 D-{dday}" if dday is not None else "") + note,
                                   "high" if dday is not None and dday <= 7 else "normal", base))
            elif not rebid:
                cand.append(_alert("NEW_BID", b["hospital_id"], f"NEW_BID:{b['bid_key']}", f"{b['hospital']} — {b['title']}",
                                   f"예산 {fmt_won(b['budget'])}" + (f" · 마감 D-{dday}" if dday is not None else "") + tagtxt,
                                   "high" if dday is not None and dday <= 7 else "normal", base))

    # 2) 마감 임박: 진행중 공고가 D-7 / D-3 / D-1 에 처음 도달할 때 한 번씩 (이미 지난 D-day 는 가장 가까운 것 하나만)
    if not bids.empty:
        for _, b in bids[bids["deadline"].notna()].iterrows():
            d = (b["deadline"].normalize() - t).days
            if not 0 <= d <= max(DEADLINE_DAYS):
                continue
            n = min(x for x in DEADLINE_DAYS if d <= x)
            tags = list(b["product_tags"]) if isinstance(b.get("product_tags"), (list, tuple)) else []
            cand.append(_alert("DEADLINE", b["hospital_id"], f"DL:{b['bid_key']}:{n}", f"{b['hospital']} — {b['title']}",
                               f"마감 D-{d} ({b['deadline']:%m/%d %H:%M}) · 예산 {fmt_won(b['budget'])}", "high" if n <= 3 else "normal",
                               {"title": b["title"], "bid_ntce_no": b["bid_ntce_no"], "tags": tags, "days": n, "deadline": b["deadline"].isoformat()}))

    # 3) 계약만료 마일스톤 (D-90/60/30/7 도달 시 1회) — 종료일 정보가 있는 계약만
    con = pharma_only(snap.contracts)
    if not con.empty:
        con = con[con["end_date"].notna()]
        days = (con["end_date"] - t).dt.days
        for row, d in zip(con.itertuples(), days):
            hit = [m for m in EXPIRY_MILESTONES if d <= m and d >= 0]       # 예: d=75 → 90 도달
            if not hit:
                continue
            m = min(hit)
            cand.append(_alert("CONTRACT_EXPIRY", row.hospital_id, f"EXP:{row.contract_key}:{m}",
                               f"{row.hospital} — 계약종료 D-{d}",
                               f"{row.title} · {row.vendor_name or '-'} · {fmt_won(row.contract_amount)} · 종료 {row.end_date.date()}",
                               "high" if m <= 30 else "normal",
                               {"title": row.title, "vendor": row.vendor_name, "end_date": str(row.end_date.date())}))

    # 4) 낙찰 결과 (자사 제외는 받는 사람의 회사 기준이라 발송·표시 때 거른다) / 5) 유찰
    since = t - pd.Timedelta(days=lookback_days + 4)
    aw = pharma_only(snap.awards)
    if not aw.empty:
        for a in aw[aw["award_date"] >= since].itertuples():
            tags = list(a.product_tags) if isinstance(getattr(a, "product_tags", None), (list, tuple)) else []
            cand.append(_alert("AWARD", a.hospital_id, f"AWD:{a.award_key}", f"{a.hospital} — {a.title}",
                               f"낙찰 {a.winner_name} · {fmt_won(a.award_amount)}", "normal",
                               {"title": a.title, "winner": a.winner_name, "bid_ntce_no": a.bid_ntce_no, "tags": tags}))
    fl = pharma_only(snap.failed)
    if not fl.empty:
        for a in fl[fl["award_date"] >= since].itertuples():
            tags = list(a.product_tags) if isinstance(getattr(a, "product_tags", None), (list, tuple)) else []
            cand.append(_alert("FAILED", a.hospital_id, f"FL:{a.award_key}", f"{a.hospital} — {a.title}",
                               "유찰 · 낙찰자 없음 (재공고가 나올 수 있음)", "normal",
                               {"title": a.title, "bid_ntce_no": a.bid_ntce_no, "tags": tags}))

    fresh = [c for c in cand if c["dedup_key"] not in existing]
    repo.upsert("alerts", fresh)
    return fresh


def _alert(kind: str, hospital_id, key: str, title: str, message: str, severity: str, payload: dict | None = None) -> dict:
    return {"alert_type": kind, "hospital_id": None if pd.isna(hospital_id) else int(hospital_id),
            "dedup_key": key, "title": title, "message": message, "severity": severity,
            "delivered_to": [], "payload": payload or {}}


def recipients_for(alert: dict, users: list[dict], subs: list[dict],
                   own_aliases_by_company: dict | None = None) -> list[dict]:
    """[예전 방식] 알림 조건을 저장하지 않은 사용자: 구독(subscriptions)한 병원·종류로만 받는다.
    낙찰 알림은 받는 사람 회사의 자사(표기명)가 낙찰받은 건이면 보내지 않는다."""
    from ..collectors.competitors import matches_any_alias
    from .alert_rules import alert_winner

    kind = "COMPETITOR_AWARD" if alert["alert_type"] == "AWARD" else alert["alert_type"]
    winner = alert_winner(alert)
    by_user: dict[int, list[dict]] = {}
    for s in subs:
        by_user.setdefault(s["user_id"], []).append(s)
    out = []
    for u in users:
        if not u.get("is_active", True):
            continue
        if kind == "COMPETITOR_AWARD" and matches_any_alias(winner, (own_aliases_by_company or {}).get(u.get("company_id"), [])):
            continue
        for s in by_user.get(u["id"], []):
            types = s.get("alert_types") or list(LEGACY_ALERT_TYPES)
            if kind in types and s.get("hospital_id") in (None, alert.get("hospital_id")):
                out.append(u)
                break
    return out
