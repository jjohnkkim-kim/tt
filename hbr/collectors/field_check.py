"""나라장터 실제 응답 ↔ normalize.FIELDS 후보 점검 (필드 매핑 검증 도구).

실제 키로 소량 호출한 응답을 분석해 ①어떤 논리 필드가 어떤 응답 필드에 매칭되는지 ②채워진 비율
③날짜·금액 파싱 성공률 ④매칭 안 된 필드(수정 힌트) ⑤병원 필터 통과/정규화 결과를 보고한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from ..etl.normalize import FIELDS, IMPORTANT, REQUIRED, normalize_award, normalize_bid, normalize_contract
from ..utils import parse_date, parse_dt, to_amount
from .g2b import pick
from .hospital_filter import is_hospital

# 논리 필드의 값 종류 (파싱 점검용)
KIND = {"bid_date": "date", "deadline": "datetime", "open_date": "date", "date": "date", "contract_date": "date",
        "start": "date", "end": "date", "budget": "amount", "est_price": "amount", "amount": "amount", "rate": "amount"}

# 후보에 없을 때 응답 키에서 찾아볼 단서 (소문자 정규식)
HINTS = {
    "inst": r"insttnm|orgnm|agencynm", "no": r"ntceno|cntrctno|bidno|unty", "title": r"ntcenm|cntrctnm|bidnm|ttl",
    "bid_date": r"ntcedt|ntcedate|rgstdt|ntcebgn", "deadline": r"clse|cls", "budget": r"bdgt|prce|amt",
    "winner": r"bidwinnr|sucsfbid|scsbid|winnr", "amount": r"amt", "date": r"opengdt|opengdate|sucsfdate|dt$",
    "vendor": r"corp|cmpny|entrps", "end": r"end|ttal", "contract_date": r"cncls|cntrctdate",
    "start": r"bgn|strt|begin", "open_date": r"openg", "bid_method": r"mthd|methd", "url": r"url",
}


@dataclass
class FieldStat:
    logical: str
    matched: str | None            # 실제로 매칭된 응답 필드명
    filled: float                  # 채워진 비율 (0~1)
    parsed: float | None = None    # 파싱 성공 비율 (날짜/금액 필드만)
    sample: str | None = None
    hints: list[str] = field(default_factory=list)


@dataclass
class FieldReport:
    dataset: str
    operation: str = ""
    params: dict = field(default_factory=dict)
    total: int = 0
    scanned: int = 0
    hospital_rows: int = 0
    normalized: int = 0
    keys: list[str] = field(default_factory=list)
    unmapped: list[str] = field(default_factory=list)
    stats: list[FieldStat] = field(default_factory=list)
    missing_required: list[str] = field(default_factory=list)
    missing_important: list[str] = field(default_factory=list)
    normalized_sample: list[dict] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.scanned > 0 and not self.missing_required


def _filled(v) -> bool:
    return v not in (None, "", "null")


def _inst_of(row: dict, dataset: str) -> str | None:
    return next((str(row[k]) for k in FIELDS[dataset]["inst"] if _filled(row.get(k))), None)


def collect_sample(client, dataset: str, start: date, end: date, max_rows: int = 300, scan_limit: int = 3000,
                   want_hospital: int = 20) -> tuple[list[dict], list[dict], int]:
    """(전체 표본, 병원 표본, 스캔 건수). 병원 표본이 충분하거나 scan_limit 에 도달하면 중단."""
    rows: list[dict] = []
    hosp: list[dict] = []
    scanned = 0
    for raw in client.fetch(dataset, start, end):
        scanned += 1
        if len(rows) < max_rows:
            rows.append(raw)
        if is_hospital(_inst_of(raw, dataset)) and len(hosp) < want_hospital:
            hosp.append(raw)
        if scanned >= scan_limit or (len(rows) >= max_rows and len(hosp) >= want_hospital):
            break
    return rows, hosp, scanned


def analyze(dataset: str, rows: list[dict], hospital_rows: list[dict], competitors: list[dict],
            scanned: int | None = None) -> FieldReport:
    rep = FieldReport(dataset=dataset, scanned=scanned if scanned is not None else len(rows),
                      hospital_rows=len(hospital_rows))
    keys: list[str] = sorted({k for r in rows for k in r})
    rep.keys = keys
    used: set[str] = set()
    for logical, cands in FIELDS[dataset].items():
        # 후보 중 표본에서 가장 많이 채워진 필드를 '매칭'으로 본다
        counts = {c: sum(1 for r in rows if _filled(r.get(c))) for c in cands if c in keys}
        matched = max(counts, key=counts.get) if counts else None
        n = len(rows) or 1
        st = FieldStat(logical, matched, (counts[matched] / n) if matched else 0.0)
        if matched:
            used.update(c for c in cands if c in keys)
            vals = [r[matched] for r in rows if _filled(r.get(matched))]
            st.sample = str(vals[0])[:60] if vals else None
            kind = KIND.get(logical)
            if kind and vals:
                parse = {"date": parse_date, "datetime": parse_dt, "amount": to_amount}[kind]
                st.parsed = sum(1 for v in vals if parse(v) is not None) / len(vals)
        rep.stats.append(st)
    rep.unmapped = [k for k in keys if k not in used]
    for st in rep.stats:
        if st.matched is None or st.filled < 0.95:          # 일부 행만 채워지면 다른 이름의 필드가 섞여 있을 수 있음
            rx = HINTS.get(st.logical)
            st.hints = [k for k in rep.unmapped if rx and re.search(rx, k.lower())][:5]
    by = {s.logical: s for s in rep.stats}
    rep.missing_required = [f for f in REQUIRED[dataset] if by[f].matched is None or by[f].filled == 0]
    rep.missing_important = [f for f in IMPORTANT[dataset] if by[f].matched is None or by[f].filled == 0]

    fn = {"bids": lambda r: normalize_bid(r), "awards": lambda r: normalize_award(r, competitors),
          "contracts": lambda r: normalize_contract(r, competitors)}[dataset]
    out = [x for x in (fn(r) for r in hospital_rows) if x]
    rep.normalized = len(out)
    rep.normalized_sample = [{k: v for k, v in x.items() if k != "raw"} for x in out[:3]]
    return rep


def render(rep: FieldReport) -> str:
    L = [f"\n=== {rep.dataset} ({rep.operation}) ==="]
    if rep.error:
        return "\n".join(L + [f"  ✗ 호출 실패: {rep.error}"])
    L.append(f"  요청 파라미터: {rep.params}  전체 건수(totalCount): {rep.total:,}")
    L.append(f"  스캔 {rep.scanned:,}건 / 병원 필터 통과 {rep.hospital_rows}건 / 정규화 성공 {rep.normalized}건")
    if rep.scanned == 0:
        L.append("  ✗ 응답이 비어 있습니다 — 조회 기간/파라미터명/오퍼레이션명을 확인하세요 (--days 늘려보기)")
        return "\n".join(L)
    L.append(f"  응답 필드 {len(rep.keys)}개: {', '.join(rep.keys)}")
    L.append("\n  논리필드         매칭된 응답필드          채움   파싱   예시값")
    for s in rep.stats:
        flag = "✗" if s.matched is None or s.filled == 0 else ("△" if (s.parsed is not None and s.parsed < 0.9) or s.filled < 0.5 or s.hints else "✓")
        parsed = f"{s.parsed:>4.0%}" if s.parsed is not None else "   -"
        L.append(f"  {flag} {s.logical:<15} {(s.matched or '(없음)'):<22} {s.filled:>4.0%}  {parsed}  {s.sample or ''}")
        if s.hints:
            L.append(f"      ↳ 후보 추정: {', '.join(s.hints)}  → hbr/etl/normalize.py FIELDS['{rep.dataset}']['{s.logical}'] 에 추가")
    if rep.unmapped:
        L.append(f"\n  어디에도 매핑되지 않은 응답 필드: {', '.join(rep.unmapped)}")
    if rep.hospital_rows and rep.normalized < rep.hospital_rows:
        L.append(f"  ⚠ 병원 {rep.hospital_rows}건 중 {rep.hospital_rows - rep.normalized}건이 정규화에서 탈락 (필수 필드 누락)")
    if rep.hospital_rows == 0:
        L.append("  ⚠ 병원 기관이 표본에 없어 정규화 결과를 확인하지 못했습니다 (--days / --scan-limit 를 늘려보세요)")
    for x in rep.normalized_sample[:2]:
        L.append("  정규화 예: " + ", ".join(f"{k}={v}" for k, v in x.items() if v not in (None, [], "")))
    if rep.missing_required:
        L.append(f"\n  ✗ 필수 필드 미매칭: {', '.join(rep.missing_required)} — 이 상태로는 행이 저장되지 않습니다")
    if rep.missing_important:
        L.append(f"  △ 중요 필드 미매칭: {', '.join(rep.missing_important)} — 해당 기능(마감 알림/금액 집계/계약만료 등)이 약해집니다")
    if rep.ok and not rep.missing_important:
        L.append("\n  ✓ 필드 매핑 정상")
    return "\n".join(L)
