"""관리자 운영 현황: 회사·사용자·요금제·수집·메일 상태를 한눈에."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from .auth import accounts
from .plans import PLANS, plan_of


def _ts(v):
    try:
        return pd.to_datetime(v, utc=True)
    except Exception:       # noqa: BLE001
        return pd.NaT


def overview(repo, today: date | None = None) -> dict:
    today = today or date.today()
    users, companies = repo.rows("users"), repo.list_companies()
    by_company = Counter(u.get("company_id") for u in users)
    prods = Counter(p["company_id"] for p in repo.rows("company_products"))
    table = pd.DataFrame([{"회사": c["name"], "유형": c.get("company_type"), "플랜": PLANS[plan_of(c, today)]["label"],
                           "기한": c.get("plan_until") or "-", "사용자": by_company.get(c["id"], 0), "제품": prods.get(c["id"], 0),
                           "company_id": c["id"]} for c in companies],
                         columns=["회사", "유형", "플랜", "기한", "사용자", "제품", "company_id"])
    status = Counter(accounts.status_of(u) for u in users)
    runs = pd.DataFrame(repo.rows("pipeline_runs", order="-id", limit=30))
    mails = pd.DataFrame(repo.rows("email_reports", order="-id", limit=200))
    since = pd.Timestamp(today - timedelta(days=7))
    recent_mail = mails[pd.to_datetime(mails["report_date"], errors="coerce") >= since] if not mails.empty else mails
    last_ok = None
    if not runs.empty:
        ok = runs[runs["status"] == "success"]
        last_ok = None if ok.empty else _ts(ok.iloc[0]["finished_at"] or ok.iloc[0]["started_at"])
    return {"companies": len(companies), "users": len(users), "pending": status.get("pending", 0),
            "active": sum(1 for u in users if accounts.status_of(u) == "approved" and u.get("is_active", True)),
            "plan_counts": Counter(PLANS[plan_of(c, today)]["label"] for c in companies), "table": table,
            "no_company_users": by_company.get(None, 0), "last_success": last_ok,
            "recent_failures": int((runs["status"] == "failed").head(10).sum()) if not runs.empty else 0,
            "mail_7d": {"sent": int((recent_mail["status"] == "sent").sum()) if not recent_mail.empty else 0,
                        "failed": int((recent_mail["status"] == "failed").sum()) if not recent_mail.empty else 0}}
