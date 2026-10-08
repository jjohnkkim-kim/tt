"""페이지 공용: 캐시된 Repo/스냅샷/점수, 표 변환·다운로드 헬퍼."""
from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from hbr.analytics.data import Snapshot, load_snapshot
from hbr.analytics.scoring import Opportunity, compute_opportunities
from hbr.store.repo import Repo, get_repo
from hbr.utils import today_kst


@st.cache_resource(show_spinner="데이터 저장소 연결 중…")
def repo() -> Repo:
    return get_repo()


def company_id() -> int | None:
    """로그인한 사용자의 소속 회사. 회사별 데이터는 항상 여기서만 가져온다 (화면 입력값은 쓰지 않는다)."""
    return getattr(st.session_state.get("user"), "company_id", None)


# 아래 캐시는 모두 company_id 를 인자로 받아 회사마다 따로 저장된다 (회사 간에 결과가 섞이지 않는다)
@st.cache_data(ttl=300, show_spinner="데이터 불러오는 중…")
def _snapshot(cid: int | None) -> Snapshot:
    return load_snapshot(repo(), repo().own_aliases(cid))


@st.cache_data(ttl=300, show_spinner=False)
def _opportunities(cid: int | None) -> list[Opportunity]:
    return compute_opportunities(_snapshot(cid), today_kst())


@st.cache_data(ttl=300, show_spinner=False)
def _lifecycle(cid: int | None):
    """공고별 단계(신규/진행중/낙찰/유찰/계약완료…)와 낙찰·계약 연결 정보. snapshot().bids 와 같은 인덱스."""
    from hbr.analytics.lifecycle import build_lifecycle

    return build_lifecycle(_snapshot(cid), today_kst())


@st.cache_data(ttl=300, show_spinner=False)
def _matches(cid: int | None):
    """이 회사의 관심 제품과 입찰공고의 매칭 결과 (snapshot().bids 와 같은 인덱스). 다른 회사 제품은 쓰지 않는다."""
    from hbr.analytics.matching import match_frame

    return match_frame(_snapshot(cid).bids, repo().list_products(cid))


@st.cache_data(ttl=300, show_spinner=False)
def _company_opps(cid: int | None):
    """이 회사 관심제품 기준 병원별 기회 점수 (관심제품이 없으면 빈 표)."""
    from hbr.analytics.opportunity import company_opportunities

    if not _products(cid):                       # 관심제품이 없으면 점수를 만들지 않는다
        return pd.DataFrame()
    return company_opportunities(_snapshot(cid), _matches(cid), today_kst())


@st.cache_data(ttl=300, show_spinner=False)
def _products(cid: int | None) -> list[dict]:
    return repo().list_products(cid)


def matches():
    return _matches(company_id())


def company_opps():
    return _company_opps(company_id())


def my_products() -> list[dict]:
    return _products(company_id())


def snapshot() -> Snapshot:
    return _snapshot(company_id())


def opportunities() -> list[Opportunity]:
    return _opportunities(company_id())


def lifecycle():
    return _lifecycle(company_id())


def refresh_button() -> None:
    if st.sidebar.button("데이터 새로고침", icon=":material/refresh:", width="stretch"):
        st.cache_data.clear()
        st.rerun()


def current_user():
    return st.session_state["user"]


def to_xlsx(df: pd.DataFrame, sheet: str = "data") -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name=sheet)
    return buf.getvalue()


def download_buttons(df: pd.DataFrame, name: str) -> None:
    """다운로드는 RBAC('download' 권한) 필요 — 데이터 반출 통제."""
    if not current_user().can("download"):
        st.caption("🔒 다운로드는 영업(sales) 이상 권한에서 가능합니다.")
        return
    c1, c2, _ = st.columns([1, 1, 4])
    c1.download_button("⬇ Excel", to_xlsx(df), f"{name}.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    c2.download_button("⬇ CSV", df.to_csv(index=False).encode("utf-8-sig"), f"{name}.csv", "text/csv")


def won_billion(v) -> float | None:
    return None if v is None or pd.isna(v) else round(float(v) / 1e8, 2)


def date_str(s: pd.Series, fmt="%Y-%m-%d") -> pd.Series:
    return s.dt.strftime(fmt).fillna("-")


def empty_notice(df: pd.DataFrame, msg: str = "표시할 데이터가 없습니다. 수집 파이프라인을 먼저 실행하세요.") -> bool:
    if df is None or df.empty:
        st.info(msg)
        return True
    return False
