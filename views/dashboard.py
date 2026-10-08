from html import escape

import pandas as pd
import plotly.express as px
import streamlit as st

from hbr.analytics.actions import recommend_actions
from hbr.analytics.data import pharma_only
from hbr.analytics.metrics import kpis
from hbr.constants import SCORE_LABELS, SCORE_WEIGHTS
from hbr.utils import fmt_won, today_kst

from views import _ui
from views._common import opportunities, snapshot

_ui.page_header("대시보드", "의약품 관련 입찰 현황과 영업 우선순위를 한눈에", "OVERVIEW")
snap, opps, today = snapshot(), opportunities(), today_kst()
k = kpis(snap, opps, today)
st.caption(f"기준일 {today} · 의약품 관련 입찰/계약만 집계 (병원 필터 적용)")

c = st.columns(6)
c[0].metric(f"신규 입찰 ({k['new_days']}일)", f"{k['new_bids']}건")
c[1].metric("진행중 입찰", f"{k['open_bids']}건")
c[2].metric("마감 임박 (7일)", f"{k['closing_soon']}건")
c[3].metric("계약 종료 예정 (90일)", f"{k['expiring_90']}건")
c[4].metric("경쟁사 신규 수주 (30일)", f"{k['competitor_awards_30d']}건")
c[5].metric("예상 기회금액", fmt_won(k["expected_amount"]),
            help="진행중 입찰 예산 + 180일 내 종료 계약 금액의 합계 (추정)")

_ui.section("Opportunity Score TOP 10")
if not opps:
    st.info("점수를 계산할 데이터가 없습니다.")
else:
    top = opps[:10]
    df = pd.DataFrame([{
        "순위": i + 1, "병원": o.hospital, "점수": o.score, "등급": o.grade,
        "계약종료": f"D-{o.days_to_expiry}" if o.days_to_expiry is not None and o.days_to_expiry >= 0 else "-",
        "예상기회": fmt_won(o.est_amount), "근거": " · ".join(o.reasons[:3])} for i, o in enumerate(top)])
    st.dataframe(df, hide_index=True, width="stretch", column_config={
        "점수": st.column_config.ProgressColumn("점수", min_value=0, max_value=100, format="%.1f")})

    left, right = st.columns([1, 1])
    pick = left.selectbox("병원 선택 → 점수 구성 / 추천 Action", [o.hospital for o in top])
    o = next(x for x in top if x.hospital == pick)
    comp = pd.DataFrame({"항목": [f"{SCORE_LABELS[k]} ({int(SCORE_WEIGHTS[k]*100)}%)" for k in SCORE_WEIGHTS],
                         "점수": [o.components[k] for k in SCORE_WEIGHTS]})
    fig = px.bar(comp, x="점수", y="항목", orientation="h", range_x=[0, 100], text="점수", height=260)
    fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), yaxis_title=None)
    left.plotly_chart(fig, width="stretch")
    with right.container(border=True):
        st.markdown(f'<div class="hbr-detail-title">{escape(o.hospital)}</div>', unsafe_allow_html=True)
        st.markdown(_ui.chips([f"{o.score}점"]) + _ui.chips([o.grade], "gray"), unsafe_allow_html=True)
        reasons = [r for r in o.reasons if r]
        if reasons:
            st.markdown('<ul class="hbr-reasons">' + "".join(f"<li>{escape(r)}</li>" for r in reasons) + "</ul>", unsafe_allow_html=True)
        st.markdown("**추천 Action**")
        st.markdown("".join(_ui.action_row(a.urgency, a.text) for a in recommend_actions(o)), unsafe_allow_html=True)
        if o.expected_rebid:
            st.caption(f"예상 재입찰 시점(추정): {o.expected_rebid}")

_ui.section("낙찰 추이")
aw = pharma_only(snap.awards)
if aw.empty:
    st.info("낙찰 데이터가 없습니다.")
else:
    m = aw.assign(month=aw["award_date"].dt.to_period("M").dt.to_timestamp()).groupby(["month", "competitor"])["award_amount"].sum().reset_index()
    m["억원"] = m["award_amount"] / 1e8
    fig = px.bar(m, x="month", y="억원", color="competitor", height=320, labels={"month": "", "competitor": "업체"})
    fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), legend_title=None)
    st.plotly_chart(fig, width="stretch")
