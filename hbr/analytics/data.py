"""분석용 데이터 스냅샷: 테이블을 한 번 읽어 공통 가공."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from ..collectors.competitors import matches_any_alias
from ..constants import OTHER_COMPETITOR
from ..store.repo import Repo


@dataclass
class Snapshot:
    hospitals: pd.DataFrame
    competitors: pd.DataFrame
    bids: pd.DataFrame
    awards: pd.DataFrame
    contracts: pd.DataFrame
    failed: pd.DataFrame = field(default_factory=pd.DataFrame)      # 유찰 (낙찰 분석에는 섞이지 않게 따로 둔다)

    def hospital_name(self, hid) -> str:
        r = self.hospitals.loc[self.hospitals["id"] == hid, "name"]
        return r.iloc[0] if len(r) else f"#{hid}"


def _latest_revision(bids: pd.DataFrame) -> pd.DataFrame:
    """같은 공고번호의 재공고/정정은 최신 차수만."""
    if bids.empty:
        return bids
    return (bids.sort_values(["bid_ntce_no", "bid_ntce_ord"])
                .drop_duplicates("bid_ntce_no", keep="last"))


def _with_times(bids: pd.DataFrame) -> pd.DataFrame:
    """종료일시(deadline)·개찰일시(open_at)를 시각까지 채운다.
    전자입찰이 아닌 공고는 나라장터 API 가 종료일시를 주지 않으므로 개찰일시로 대신하고 deadline_estimated 로 표시한다."""
    if bids.empty:
        return bids
    from ..etl.normalize import raw_dt

    def raw_of(v) -> dict:
        if isinstance(v, str):
            try:
                v = json.loads(v)
            except ValueError:
                return {}
        return v if isinstance(v, dict) else {}

    raws = bids["raw"].map(raw_of) if "raw" in bids else pd.Series([{}] * len(bids), index=bids.index)
    stored = bids["deadline"] if "deadline" in bids else pd.Series(pd.NaT, index=bids.index)
    close = pd.to_datetime(raws.map(lambda r: raw_dt(r, "bidClseDt", "bidClseDate", "bidClseTm")), errors="coerce")
    opened = pd.to_datetime(raws.map(lambda r: raw_dt(r, "opengDt", "opengDate", "opengTm")), errors="coerce")
    if "open_date" in bids:
        opened = opened.fillna(pd.to_datetime(bids["open_date"], errors="coerce"))
    bids = bids.copy()
    bids["open_at"] = opened
    known = close.fillna(pd.to_datetime(stored, errors="coerce"))
    bids["deadline_estimated"] = known.isna() & opened.notna()
    bids["deadline"] = known.fillna(opened)
    return bids


def when_text(r, mode: str = "new", year: bool = False) -> str:
    """공고 한 건의 '등록 · 마감 · 개찰' 한 줄. mode=closing 이면 등록일을 뺀다."""
    fmt = "%Y-%m-%d %H:%M" if year else "%m/%d %H:%M"
    get = r.get if hasattr(r, "get") else lambda k, d=None: getattr(r, k, d)
    ok = lambda v: v is not None and not pd.isna(v)
    bd, dl, op = get("bid_date"), get("deadline"), get("open_at")
    parts = []
    if mode != "closing" and ok(bd):
        parts.append(f"등록 {bd:%m/%d}")
    parts.append(f"마감 {dl:{fmt}}" + ("(추정)" if bool(get("deadline_estimated", False)) else "") if ok(dl) else "마감 미정")
    parts.append(f"개찰 {op:{fmt}}" if ok(op) else "개찰 미정")
    return " · ".join(parts)


def load_snapshot(repo: Repo, own_aliases: list[str] | tuple[str, ...] = ()) -> Snapshot:
    hospitals = repo.df("hospitals")
    competitors = repo.df("competitors")
    bids = _with_times(_latest_revision(repo.df("bids")))
    awards, contracts = repo.df("awards"), repo.df("contracts")
    failed = pd.DataFrame()
    if not awards.empty and "result_status" in awards:
        failed = awards[awards["result_status"] == "유찰"].copy()
        awards = awards[awards["result_status"] != "유찰"].copy()
    comp_name = dict(zip(competitors.get("id", []), competitors.get("name", [])))
    own_aliases = [a for a in (own_aliases or []) if str(a).strip()]
    for df in (awards, contracts):
        if df.empty:
            df["competitor"], df["is_own"] = pd.Series(dtype=object), pd.Series(dtype=bool)
            continue
        if "competitor_id" not in df:
            df["competitor_id"] = None
        df["competitor"] = df["competitor_id"].map(comp_name).fillna(OTHER_COMPETITOR)
        name_col = "winner_name" if "winner_name" in df else "vendor_name"       # 자사 여부는 이 회사가 등록한 표기명으로 판단한다
        df["is_own"] = df[name_col].map(lambda n: matches_any_alias(n, own_aliases)).astype(bool) if name_col in df else False
    for df in (bids, awards, contracts, failed):
        if not df.empty and "hospital_id" in df:
            df["hospital"] = df["hospital_id"].map(dict(zip(hospitals["id"], hospitals["name"])))
    return Snapshot(hospitals, competitors, bids, awards, contracts, failed)


def pharma_only(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "is_pharma" not in df:
        return df
    return df[df["is_pharma"].fillna(False).astype(bool)]


def open_bids(bids: pd.DataFrame, today: date) -> pd.DataFrame:
    if bids.empty:
        return bids
    t = pd.Timestamp(today)
    return bids[bids["deadline"].isna() | (bids["deadline"] >= t)]
