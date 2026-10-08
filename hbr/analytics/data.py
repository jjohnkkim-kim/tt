"""분석용 데이터 스냅샷: 테이블을 한 번 읽어 공통 가공."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from ..constants import OTHER_COMPETITOR
from ..store.repo import Repo


@dataclass
class Snapshot:
    hospitals: pd.DataFrame
    competitors: pd.DataFrame
    bids: pd.DataFrame
    awards: pd.DataFrame
    contracts: pd.DataFrame

    def hospital_name(self, hid) -> str:
        r = self.hospitals.loc[self.hospitals["id"] == hid, "name"]
        return r.iloc[0] if len(r) else f"#{hid}"


def _latest_revision(bids: pd.DataFrame) -> pd.DataFrame:
    """같은 공고번호의 재공고/정정은 최신 차수만."""
    if bids.empty:
        return bids
    return (bids.sort_values(["bid_ntce_no", "bid_ntce_ord"])
                .drop_duplicates("bid_ntce_no", keep="last"))


def load_snapshot(repo: Repo) -> Snapshot:
    hospitals = repo.df("hospitals")
    competitors = repo.df("competitors")
    bids = _latest_revision(repo.df("bids"))
    awards, contracts = repo.df("awards"), repo.df("contracts")
    comp_name = dict(zip(competitors.get("id", []), competitors.get("name", [])))
    comp_own = dict(zip(competitors.get("id", []), competitors.get("is_own", [])))
    for df in (awards, contracts):
        if df.empty:
            df["competitor"], df["is_own"] = pd.Series(dtype=object), pd.Series(dtype=bool)
            continue
        if "competitor_id" not in df:
            df["competitor_id"] = None
        df["competitor"] = df["competitor_id"].map(comp_name).fillna(OTHER_COMPETITOR)
        df["is_own"] = df["competitor_id"].map(comp_own).fillna(False).astype(bool)
    for df in (bids, awards, contracts):
        if not df.empty and "hospital_id" in df:
            df["hospital"] = df["hospital_id"].map(dict(zip(hospitals["id"], hospitals["name"])))
    return Snapshot(hospitals, competitors, bids, awards, contracts)


def pharma_only(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "is_pharma" not in df:
        return df
    return df[df["is_pharma"].fillna(False).astype(bool)]


def open_bids(bids: pd.DataFrame, today: date) -> pd.DataFrame:
    if bids.empty:
        return bids
    t = pd.Timestamp(today)
    return bids[bids["deadline"].isna() | (bids["deadline"] >= t)]
