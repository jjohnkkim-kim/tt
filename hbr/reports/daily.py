"""Daily Report 생성: 데이터 집계 → (선택) AI 브리핑 → HTML/텍스트 렌더."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..analytics.actions import recommend_actions
from ..analytics.data import Snapshot, load_snapshot, open_bids, pharma_only
from ..analytics.metrics import expiring_contracts
from ..analytics.scoring import Opportunity, compute_opportunities
from ..utils import fmt_won, today_kst

TEMPLATES = Path(__file__).parent / "templates"
_env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html", "j2"]))
_env.filters["won"] = fmt_won


def _lookback(today: date) -> int:
    """월요일 리포트는 주말(토·일) 공고까지 포함."""
    return 3 if today.weekday() == 0 else 1


def build_report(snap: Snapshot, opps: list[Opportunity], today: date | None = None,
                 watched: set[int] | None = None, user_name: str | None = None,
                 briefing: str | None = None) -> dict:
    today = today or today_kst()
    t = pd.Timestamp(today)
    watched = watched or set()
    bids = pharma_only(snap.bids)
    lb = _lookback(today)

    new_bids = bids[bids["bid_date"] >= t - pd.Timedelta(days=lb - 1)] if not bids.empty else bids
    ob = open_bids(bids, today)
    closing = ob[ob["deadline"].notna() & (ob["deadline"] <= t + pd.Timedelta(days=7, hours=23))] if not ob.empty else ob
    exp = expiring_contracts(snap, today, 90)
    aw = pharma_only(snap.awards)
    comp_awards = aw[(~aw["is_own"]) & (aw["award_date"] >= t - pd.Timedelta(days=7))] if not aw.empty else aw

    def bid_rows(df, n=15):
        if df.empty:
            return []
        df = df.assign(is_watched=df["hospital_id"].isin(watched)).sort_values(["is_watched", "budget"], ascending=[False, False])
        return [{"hospital": r.hospital, "title": r.title, "budget": r.budget, "watched": r.is_watched,
                 "deadline": r.deadline.strftime("%m/%d") if pd.notna(r.deadline) else "-",
                 "dday": (r.deadline.normalize() - t).days if pd.notna(r.deadline) else None}
                for r in df.head(n).itertuples()]

    top = opps[:10]
    issues = []
    focus = [o for o in opps if o.hospital_id in watched] or opps[:5]
    for o in focus[:8]:
        issues.append({"hospital": o.hospital, "watched": o.hospital_id in watched,
                       "lines": o.reasons or ["특이사항 없음"], "score": o.score})

    return {
        "date": today, "user_name": user_name, "briefing": briefing,
        "summary": {"new_bids": len(new_bids), "closing": len(closing), "expiring": len(exp),
                    "competitor_awards": len(comp_awards)},
        "lookback_days": lb,
        "new_bids": bid_rows(new_bids),
        "closing": bid_rows(closing.sort_values("deadline") if not closing.empty else closing),
        "expiring": [{"hospital": r.hospital, "title": r.title, "vendor": r.vendor_name or "-",
                      "amount": r.contract_amount, "end": r.end_date.strftime("%Y-%m-%d"), "d": int(r.d_day),
                      "estimated": bool(r.end_date_estimated), "watched": r.hospital_id in watched}
                     for r in exp.head(15).itertuples()],
        "competitor_awards": [{"competitor": r.competitor if r.competitor != "기타" else r.winner_name,
                               "hospital": r.hospital, "amount": r.award_amount,
                               "date": r.award_date.strftime("%m/%d") if pd.notna(r.award_date) else "-"}
                              for r in (comp_awards.sort_values("award_date", ascending=False).head(15).itertuples()
                                  if not comp_awards.empty else [])],
        "top": [{"rank": i + 1, "hospital": o.hospital, "score": o.score, "grade": o.grade,
                 "reasons": " · ".join(o.reasons[:3]), "watched": o.hospital_id in watched}
                for i, o in enumerate(top)],
        "actions": [{"hospital": o.hospital, "reasons": " · ".join(o.reasons[:3]),
                     "actions": [a.text for a in recommend_actions(o)[:4]]} for o in top[:3]],
        "issues": issues,
    }


def render_html(data: dict, base_url: str = "") -> str:
    return _env.get_template("daily_report.html.j2").render(r=data, base_url=base_url)


def render_text(data: dict) -> str:
    s = data["summary"]
    lines = [f"[Hospital Bid Radar] Daily Report {data['date']}",
             f"신규 입찰 {s['new_bids']}건 / 마감 임박 {s['closing']}건 / 계약만료 예정(90일) {s['expiring']}건 / "
             f"경쟁사 신규 수주 {s['competitor_awards']}건", "", "Opportunity TOP"]
    lines += [f"{t['rank']}. {t['hospital']} ({t['score']}점) {t['reasons']}" for t in data["top"][:5]]
    for a in data["actions"]:
        lines += ["", f"[AI 추천] {a['hospital']} — {a['reasons']}"] + [f"  - {x}" for x in a["actions"]]
    return "\n".join(lines)


def build_for_user(repo, user: dict | None, today: date | None = None, briefing: bool = True) -> dict:
    snap = load_snapshot(repo, repo.own_aliases(user.get("company_id")) if user else [])
    today = today or today_kst()
    opps = compute_opportunities(snap, today)
    watched = repo.watched_hospital_ids(user["id"]) if user else set()
    text = None
    if briefing:
        from ..ai.llm import executive_briefing

        text = executive_briefing(opps[:5], today)
    return build_report(snap, opps, today, watched, user.get("name") if user else None, text)
