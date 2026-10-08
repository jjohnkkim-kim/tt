from html import escape

import pandas as pd
import plotly.express as px
import streamlit as st

from hbr.analytics.metrics import bid_overview, kpis, result_counts
from hbr.config import bids_only
from hbr.utils import fmt_won, today_kst

from views import _ui
from views._common import opportunities, snapshot

_ui.page_header("대시보드", "병원 입찰공고 현황을 한눈에 확인하세요", "OVERVIEW")
snap, today = snapshot(), today_kst()

c_cap, c_tg = st.columns([4, 2])
c_cap.caption(f"기준일 {today} · 신규 = 최근 7일 공고 · 마감 임박 = 7일 이내 마감")
pharma = c_tg.toggle("의약품 관련만", value=True, help="끄면 의료기기·소모품 등 모든 병원 입찰공고를 봅니다.")

ov = bid_overview(snap.bids, today, pharma=pharma)
k = ov["kpi"]
scope = "의약품" if pharma else "전체"

c = st.columns(4)
c[0].metric(f"신규 {scope} 공고 (7일)", f"{k['new']}건")
c[1].metric(f"진행중 {scope} 공고", f"{k['open']}건")
c[2].metric("마감 임박 (7일)", f"{k['closing']}건")
c[3].metric("진행중 공고 예산 합계", fmt_won(k["budget"]), help="진행중인 공고의 예산금액 합계입니다. 예산이 없는 공고는 0원으로 계산됩니다.")

if not bids_only():          # 낙찰·계약까지 수집하는 경우에만 추가로 보여준다
    kk = kpis(snap, opportunities(), today)
    rc = result_counts(snap, today, 30, pharma)
    c2 = st.columns(4)
    c2[0].metric(f"낙찰 결과 (30일)", f"{rc['awarded']}건", help="최근 30일 개찰 결과 중 낙찰자가 정해진 공고 수")
    c2[1].metric("유찰 (30일)", f"{rc['failed']}건", help="낙찰자 없이 끝난 공고 수. 이후 재공고가 나올 수 있습니다.")
    c2[2].metric("계약 종료 임박 (90일)", f"{kk['expiring_90']}건", help="종료일 정보가 있는 의약품 계약만 집계합니다.")
    c2[3].metric("경쟁사 신규 수주 (30일)", f"{kk['competitor_awards_30d']}건")

if ov["empty"]:
    st.info("표시할 입찰공고가 없습니다. 수집이 끝나면 여기에 나타납니다.")
    st.stop()


def bid_list(df: pd.DataFrame, mode: str, limit: int = 6) -> None:
    if df.empty:
        st.caption("해당하는 공고가 없습니다.")
        return
    html = "".join(_ui.bid_item(r, today, mode) for _, r in df.head(limit).iterrows())
    st.markdown(f'<div class="hbr-list">{html}</div>', unsafe_allow_html=True)
    if len(df) > limit:
        st.caption(f"외 {len(df) - limit}건 · 전체는 '입찰공고' 메뉴에서 볼 수 있어요.")


left, right = st.columns(2)
with left:
    _ui.section(f"신규 공고 {k['new']}건")
    bid_list(ov["new"], "new")
with right:
    _ui.section(f"마감 임박 {k['closing']}건")
    bid_list(ov["closing"], "closing")

_ui.section("공고 현황")
g1, g2 = st.columns([3, 2])
with g1:
    fig = px.bar(ov["trend"], x="날짜", y="건수", height=300, title="최근 30일 공고 등록 추이")
    fig.update_layout(xaxis_title=None, yaxis_title=None, bargap=.35, title_font_size=14)
    fig.update_traces(marker_line_width=0, hovertemplate="%{x|%m/%d} · %{y}건<extra></extra>")
    st.plotly_chart(fig, width="stretch")
with g2:
    if ov["tags"].empty:
        st.markdown('<div class="hbr-empty">의약품 분류가 있는 진행중 공고가 없습니다.</div>', unsafe_allow_html=True)
    else:
        t = ov["tags"].sort_values("건수")
        fig = px.bar(t, x="건수", y="분류", orientation="h", height=300, text="건수", title="진행중 공고의 의약품 분류")
        fig.update_layout(xaxis_title=None, yaxis_title=None, title_font_size=14, xaxis_visible=False)
        fig.update_traces(marker_line_width=0, textposition="outside", cliponaxis=False)
        st.plotly_chart(fig, width="stretch")

if not ov["hospitals"].empty:
    h = ov["hospitals"].sort_values("건수")
    fig = px.bar(h, x="건수", y="기관", orientation="h", height=max(240, 38 * len(h) + 70), text="건수",
                 title="진행중 공고가 많은 기관")
    fig.update_layout(xaxis_title=None, yaxis_title=None, title_font_size=14, xaxis_visible=False)
    fig.update_traces(marker_line_width=0, textposition="outside", cliponaxis=False)
    st.plotly_chart(fig, width="stretch")

try:
    st.page_link("views/bids.py", label="전체 입찰공고 보기", icon=":material/arrow_forward:")
except Exception:   # noqa: BLE001 — 이 화면만 단독 실행(테스트)될 때는 페이지 목록이 없다
    pass
