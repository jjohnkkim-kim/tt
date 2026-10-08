"""분석용 데이터 스냅샷: 테이블을 한 번 읽어 공통 가공."""
from __future__ import annotations

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


def load_snapshot(repo: Repo, own_aliases: list[str] | tuple[str, ...] = ()) -> Snapshot:
    hospitals = repo.df("hospitals")
    competitors = repo.df("competitors")
    bids = _latest_revision(repo.df("bids"))
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
