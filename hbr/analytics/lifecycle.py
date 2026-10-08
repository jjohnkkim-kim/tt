"""입찰 lifecycle: 공고 → 개찰 → 낙찰/유찰 → 계약, 그리고 재공고 → 이전 유찰 연결.

원칙
- 공고번호가 같을 때만 '확정' 연결 (공고→낙찰/유찰, 공고→계약[계약 원문에 공고번호가 있을 때])
- 재공고 ↔ 이전 유찰은 '같은 병원 + 같은/매우 비슷한 제목'으로 **추정** 연결하고 반드시 추정이라고 표시
- 연결할 근거가 없으면 비워 둔다 (만들어 내지 않는다)
"""
from __future__ import annotations

import re
from datetime import date
from difflib import SequenceMatcher

import pandas as pd

REBID_MARKERS = ("재공고", "재입찰", "확대공고", "새로운입찰")
STATUSES = ["신규", "진행중", "개찰예정", "마감", "낙찰", "유찰", "재공고", "계약완료"]
BASIS_EXACT, BASIS_GUESS = "공고번호 일치", "제목·기관 일치(추정)"

_BRACKET = re.compile(r"\[[^\]]*\]")
_PAREN = re.compile(r"\(([^)]*)\)")
# 재공고·정정 같은 '표시'로 확인된 괄호만 지운다. (서울의료원, 카트세척기), (1그룹) 처럼 입찰을 구분하는 내용은 남긴다
_MARKER_PAREN = re.compile(r"^\s*(?:재공고|재입찰|확대공고|새로운입찰|긴급|수정|정정|연기|폐안공고|재공고|\d+차)(?:[-\s]*\d*차?)?\s*$")
_NO = re.compile(r"[^0-9A-Za-z\-]")
FUZZY_MIN = 0.92

COLUMNS = ["status", "is_rebid", "result_status", "result_date", "winner_name", "award_amount", "bidder_count",
           "contract_count", "contract_vendor", "contract_amount", "contract_date",
           "prev_ntce_no", "prev_title", "prev_date", "prev_status", "prev_basis"]


def core_title(title) -> str:
    """재공고·정정 표시([..], (재공고) 등)를 걷어 낸 비교용 제목."""
    t = _BRACKET.sub(" ", str(title or ""))
    t = _PAREN.sub(lambda m: " " if _MARKER_PAREN.match(m.group(1)) or re.fullmatch(r"(?:재공고|확대공고|재입찰)[-\s\d차]*", m.group(1).strip()) else m.group(0), t)
    t = re.sub(r"재공고|재입찰|확대공고|새로운입찰", " ", t)          # 괄호 없이 붙은 재공고 표시도 걷어 낸다 (예: '…통합구매(A) 재공고')
    return re.sub(r"\s+", "", t).lower()


def is_rebid_title(title) -> bool:
    return any(m in str(title or "") for m in REBID_MARKERS)


def clean_no(v) -> str:
    return _NO.sub("", str(v or "")).strip()


def _results(snap) -> pd.DataFrame:
    parts = []
    for df, default in ((snap.awards, "낙찰"), (snap.failed, "유찰")):
        if df is not None and not df.empty:
            d = df.copy()
            if "result_status" not in d:
                d["result_status"] = default
            parts.append(d)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def _contract_links(contracts: pd.DataFrame) -> dict[str, dict]:
    """공고번호 → 계약 요약 (계약 원문에 공고번호가 있는 계약만)."""
    if contracts is None or contracts.empty or "raw" not in contracts:
        return {}
    out: dict[str, dict] = {}
    for _, c in contracts.iterrows():
        raw = c.get("raw") if isinstance(c.get("raw"), dict) else {}
        no = clean_no(raw.get("bidNtceNo"))
        if not no:
            continue
        o = out.setdefault(no, {"count": 0, "amount": 0.0, "date": None, "vendor": None})
        o["count"] += 1
        amt = c.get("contract_amount")
        o["amount"] += 0.0 if amt is None or pd.isna(amt) else float(amt)
        d = c.get("contract_date")
        if d is not None and not pd.isna(d) and (o["date"] is None or d < o["date"]):
            o["date"], o["vendor"] = d, c.get("vendor_name")
    return out


def _status(row, res: dict | None, has_contract: bool, today: pd.Timestamp, rebid: bool) -> str:
    if has_contract:
        return "계약완료"
    if res:
        return res["result_status"]
    dl, od, bd = row.get("deadline"), row.get("open_date"), row.get("bid_date")
    closed = dl is not None and not pd.isna(dl) and dl.normalize() < today
    if closed:
        if od is not None and not pd.isna(od) and od.normalize() >= today:
            return "개찰예정"
        return "마감"
    if rebid:
        return "재공고"
    if bd is not None and not pd.isna(bd) and bd >= today - pd.Timedelta(days=1):
        return "신규"
    return "진행중"


def build_lifecycle(snap, today: date) -> pd.DataFrame:
    """snap.bids 와 같은 인덱스를 가진 lifecycle 표."""
    bids = snap.bids
    if bids is None or bids.empty:
        return pd.DataFrame(columns=COLUMNS)
    t = pd.Timestamp(today)
    res_df = _results(snap)
    best: dict[str, dict] = {}
    if not res_df.empty:
        res_df = res_df.assign(_win=(res_df["result_status"] == "낙찰").astype(int)).sort_values(["_win", "award_date"], ascending=False)
        for _, r in res_df.iterrows():
            best.setdefault(clean_no(r.get("bid_ntce_no")), r.to_dict())
    contracts = _contract_links(snap.contracts)

    # 재공고의 '이전' 후보: 같은 병원의 유찰 결과 + 더 이른 다른 공고
    cand: dict = {}
    if not res_df.empty:
        for _, r in res_df[res_df["result_status"] == "유찰"].iterrows():
            cand.setdefault(r.get("hospital_id"), []).append(
                {"no": clean_no(r.get("bid_ntce_no")), "title": r.get("title"), "date": r.get("award_date"), "status": "유찰", "core": core_title(r.get("title"))})
    for _, b in bids.iterrows():
        cand.setdefault(b.get("hospital_id"), []).append(
            {"no": clean_no(b.get("bid_ntce_no")), "title": b.get("title"), "date": b.get("bid_date"), "status": "공고", "core": core_title(b.get("title"))})

    rows = []
    for idx, b in bids.iterrows():
        no = clean_no(b.get("bid_ntce_no"))
        res = best.get(no)
        con = contracts.get(no)
        rebid = is_rebid_title(b.get("title"))
        out = dict.fromkeys(COLUMNS)
        out["is_rebid"] = rebid
        out["status"] = _status(b, res, bool(con), t, rebid)
        if res:
            out.update(result_status=res["result_status"], result_date=res.get("award_date"), winner_name=res.get("winner_name"),
                       award_amount=res.get("award_amount"), bidder_count=res.get("bidder_count") if res["result_status"] == "낙찰" else None)
        if con:
            out.update(contract_count=con["count"], contract_vendor=con["vendor"], contract_amount=con["amount"] or None, contract_date=con["date"])
        if rebid:
            prev = _find_previous(b, no, cand.get(b.get("hospital_id"), []))
            if prev:
                out.update(prev_ntce_no=prev["no"], prev_title=prev["title"], prev_date=prev["date"], prev_status=prev["status"], prev_basis=BASIS_GUESS)
        rows.append((idx, out))
    return pd.DataFrame([r for _, r in rows], index=[i for i, _ in rows], columns=COLUMNS)


def _find_previous(bid, no: str, candidates: list[dict]) -> dict | None:
    """같은 병원에서 이 재공고보다 앞선, 같거나 매우 비슷한 제목의 유찰/공고 중 가장 최근 것."""
    core, bd = core_title(bid.get("title")), bid.get("bid_date")
    best, best_key = None, None
    for c in candidates:
        if c["no"] == no or not c["core"] or not core:
            continue
        if c["date"] is None or pd.isna(c["date"]) or bd is None or pd.isna(bd) or c["date"] >= bd:
            continue
        same = c["core"] == core
        if not same:
            # 비슷한 제목으로 이을 때는 숫자(그룹 번호·품목 수·연도)가 모두 같아야 한다 — (1그룹) 과 (3그룹) 은 다른 입찰이다
            if re.findall(r"\d+", core) != re.findall(r"\d+", c["core"]):
                continue
            if min(len(core), len(c["core"])) < 8 or SequenceMatcher(None, core, c["core"]).ratio() < FUZZY_MIN:
                continue
        key = (1 if c["status"] == "유찰" else 0, c["date"])          # 유찰 이력을 우선, 그다음 가장 최근
        if best_key is None or key > best_key:
            best, best_key = c, key
    return best


def hospital_timeline(snap, hospital_id, limit: int = 200) -> pd.DataFrame:
    """병원 한 곳의 공고·개찰 결과·계약을 날짜순(최신 먼저)으로 모은 이력."""
    rows = []

    def add(df, kind, date_col, detail):
        if df is None or df.empty or "hospital_id" not in df:
            return
        for _, r in df[df["hospital_id"] == hospital_id].iterrows():
            rows.append({"날짜": r.get(date_col), "구분": kind, "제목": r.get("title"), "내용": detail(r), "공고번호": clean_no(r.get("bid_ntce_no"))})

    def money(v):
        return "" if v is None or pd.isna(v) or float(v) <= 0 else (f"{float(v) / 1e8:,.2f}억원" if float(v) >= 1e8 else f"{float(v) / 1e4:,.0f}만원")

    add(snap.bids, "공고", "bid_date", lambda r: " · ".join(x for x in (f"예산 {money(r.get('budget'))}" if money(r.get("budget")) else "", f"마감 {r['deadline']:%Y-%m-%d}" if pd.notna(r.get("deadline")) else "") if x))
    add(snap.awards, "낙찰", "award_date", lambda r: " · ".join(x for x in (str(r.get("winner_name") or ""), money(r.get("award_amount"))) if x))
    add(snap.failed, "유찰", "award_date", lambda r: "낙찰자 없음")
    if snap.contracts is not None and not snap.contracts.empty and "hospital_id" in snap.contracts:
        for _, r in snap.contracts[snap.contracts["hospital_id"] == hospital_id].iterrows():
            raw = r.get("raw") if isinstance(r.get("raw"), dict) else {}
            end = f"종료 {r['end_date']:%Y-%m-%d}" if pd.notna(r.get("end_date")) else "종료일 정보 없음"
            rows.append({"날짜": r.get("contract_date"), "구분": "계약", "제목": r.get("title"),
                         "내용": " · ".join(x for x in (str(r.get("vendor_name") or ""), money(r.get("contract_amount")), end) if x),
                         "공고번호": clean_no(raw.get("bidNtceNo"))})
    if not rows:
        return pd.DataFrame(columns=["날짜", "구분", "제목", "내용", "공고번호"])
    df = pd.DataFrame(rows)
    df["날짜"] = pd.to_datetime(df["날짜"], errors="coerce")
    return df.sort_values("날짜", ascending=False, na_position="last").head(limit).reset_index(drop=True)
