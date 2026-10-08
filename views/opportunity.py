import pandas as pd
import plotly.express as px
import streamlit as st

from hbr.analytics.data import pharma_only
from hbr.analytics.opportunity import LABELS, WEIGHTS, forecast
from hbr.utils import today_kst

from views import _ui
from views._common import company_opps, download_buttons, my_products, snapshot

_ui.page_header("기회 Radar", "내 관심제품과 맞는 공고가 많고 경쟁 여지가 있는 병원, 그리고 곧 올라올 입찰", "OPPORTUNITY")
snap, today = snapshot(), today_kst()
t_score, t_next = st.tabs(["병원별 기회 점수", "다음 입찰 예상"])

with t_score:
    if not my_products():
        st.info("설정 → 회사·관심제품에서 제품을 등록하면, 그 제품에 맞춰 병원별 점수가 계산돼요. 제품이 없으면 점수를 만들지 않습니다.")
    else:
        df = company_opps()
        if df.empty:
            st.info("점수를 계산할 데이터가 아직 없습니다.")
        else:
            st.caption("점수 = 제품 적합도 35 · 마감 임박 20 · 시장 규모 20 · 경쟁 여지 15 · 반복 구매 10. "
                       "데이터가 부족한 항목은 0점으로 깎지 않고 빼서 계산하며, 표에 '빠진 항목'으로 보여드려요.")
            min_fit = st.toggle("내 제품과 맞는 진행 공고가 있는 병원만", value=True)
            view = df[df["맞는공고"] > 0] if min_fit else df
            if view.empty:
                st.info("지금 내 제품과 맞는 진행 공고가 있는 병원이 없습니다. 위 토글을 끄면 전체 병원을 볼 수 있어요.")
            else:
                top = view.head(15)
                st.dataframe(pd.DataFrame({
                    "병원": top["병원"], "점수": top["점수"], "등급": top["등급"], "맞는 공고": top["맞는공고"], "진행 공고": top["진행공고"],
                    "근거": top["reasons"].map(" · ".join),
                    "빠진 항목(데이터 부족)": top["missing"].map(lambda m: ", ".join(LABELS[k] for k in m) or "-")}),
                    hide_index=True, width="stretch")
                pick = st.selectbox("자세히 볼 병원", list(view["병원"]), key="opp_pick")
                row = view[view["병원"] == pick].iloc[0]
                comp = pd.DataFrame({"항목": [LABELS[k] for k in WEIGHTS if k in row["components"]],
                                     "점수": [row["components"][k] for k in WEIGHTS if k in row["components"]]})
                st.plotly_chart(px.bar(comp, x="점수", y="항목", orientation="h", range_x=[0, 100], height=250, text="점수"), width="stretch")
                download_buttons(view[["병원", "점수", "등급", "맞는공고", "진행공고"]], "opportunity_scores")

with t_next:
    st.caption("같은 품목이 3회 이상 (재공고를 빼고) 새로 공고된 병원만 보여요. 평균 간격으로 계산한 **추정**이라 실제와 다를 수 있습니다.")
    horizon = st.radio("예상 시점", [30, 60, 120], index=1, horizontal=True, format_func=lambda d: f"{d}일 이내")
    fc = forecast(pharma_only(snap.bids), today, snap.hospital_name, horizon_days=horizon)
    if fc.empty:
        st.info("반복 패턴이 확인된 품목이 없습니다. 데이터 부족 — 공고가 더 쌓이면 표시됩니다.")
    else:
        out = fc.assign(**{"다음 입찰 예상(추정)": fc["다음 입찰 예상(추정)"].dt.strftime("%Y-%m-%d"),
                           "마지막 공고일": fc["마지막 공고일"].dt.strftime("%Y-%m-%d")}).drop(columns="hospital_id")
        st.dataframe(out, hide_index=True, width="stretch")
        download_buttons(out, "next_bids")
