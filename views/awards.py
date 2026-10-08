import pandas as pd
import plotly.express as px
import streamlit as st

from hbr.analytics.data import pharma_only
from hbr.analytics.metrics import share_by_year
from hbr.constants import OTHER_COMPETITOR

from views import _ui
from views._common import download_buttons, empty_notice, snapshot, won_billion

_ui.page_header("낙찰정보", "병원·업체·지역별 낙찰 분석", "AWARDS")
snap = snapshot()
aw = pharma_only(snap.awards)
fl = pharma_only(snap.failed)


def show_failed() -> None:
    """유찰: 낙찰자가 없이 끝난 입찰 — 곧 재공고가 나올 수 있어 영업 기회가 될 수 있다."""
    if fl.empty:
        st.info("유찰된 의약품 입찰이 없습니다.")
        return
    f = fl.sort_values("award_date", ascending=False)
    view = pd.DataFrame({"병원": f["hospital"], "공고명": f["title"], "개찰일": f["award_date"].dt.strftime("%Y-%m-%d"),
                         "공고번호": f["bid_ntce_no"]})
    st.caption(f"{len(view):,}건 · 유찰은 낙찰자 없이 끝난 입찰로, 이후 재공고가 나올 수 있습니다 (재공고 여부는 입찰공고에서 확인).")
    st.dataframe(view, hide_index=True, width="stretch", height=420)
    download_buttons(view, "failed_bids")


if aw.empty and fl.empty:
    empty_notice(aw)
    st.stop()
if aw.empty:
    st.info("낙찰 결과가 아직 없습니다. 유찰만 표시합니다.")
    show_failed()
    st.stop()

hosp_meta = snap.hospitals.set_index("id")[["region", "hospital_type"]]
aw = aw.join(hosp_meta, on="hospital_id")
aw["year"] = aw["award_date"].dt.year
aw["억원"] = aw["award_amount"] / 1e8

years = sorted(aw["year"].dropna().astype(int).unique())
sel_years = st.multiselect("연도", years, default=years)
aw = aw[aw["year"].isin(sel_years)]

tabs = st.tabs(["병원별", "기업별", "지역별", "연도별", "경쟁사 비교", "원본", "유찰"])
with tabs[0]:
    g = aw.groupby("hospital").agg(건수=("award_key", "count"), 억원=("억원", "sum")).reset_index().sort_values("억원", ascending=False)
    st.plotly_chart(px.bar(g.head(15), x="억원", y="hospital", orientation="h", height=420,
                           labels={"hospital": ""}).update_yaxes(autorange="reversed"), width="stretch")
    st.dataframe(g.rename(columns={"hospital": "병원"}), hide_index=True, width="stretch")
with tabs[1]:
    g = aw.groupby("winner_name").agg(건수=("award_key", "count"), 억원=("억원", "sum")).reset_index().sort_values("억원", ascending=False)
    st.plotly_chart(px.bar(g.head(15), x="억원", y="winner_name", orientation="h", height=420,
                           labels={"winner_name": ""}).update_yaxes(autorange="reversed"), width="stretch")
    st.dataframe(g.rename(columns={"winner_name": "낙찰업체"}), hide_index=True, width="stretch")
with tabs[2]:
    g = aw.assign(region=aw["region"].fillna("미분류")).groupby("region").agg(건수=("award_key", "count"), 억원=("억원", "sum")).reset_index()
    st.plotly_chart(px.pie(g, names="region", values="억원", height=380), width="stretch")
    st.caption("지역은 병원명 규칙/상급종합 목록으로 추정한 값이며 hospitals 테이블에서 보정할 수 있습니다.")
with tabs[3]:
    g = aw.groupby(["year", "competitor"])["억원"].sum().reset_index()
    st.plotly_chart(px.bar(g, x="year", y="억원", color="competitor", height=380), width="stretch")
with tabs[4]:
    sh = share_by_year(snap)
    sh = sh[sh["year"].isin(sel_years)]
    sh["share"] = (sh["share"].astype(float) * 100).round(1)
    st.plotly_chart(px.line(sh, x="year", y="share", color="competitor", markers=True, height=380,
                            labels={"share": "점유율(%)"}), width="stretch")
    pivot = sh.pivot_table(index="competitor", columns="year", values="share", fill_value=0)
    st.dataframe(pivot, width="stretch")
with tabs[5]:
    view = pd.DataFrame({"낙찰기관": aw["hospital"], "낙찰업체": aw["winner_name"], "경쟁사": aw["competitor"],
                         "낙찰금액(원)": aw["award_amount"], "낙찰일": aw["award_date"].dt.strftime("%Y-%m-%d"),
                         "공고명": aw["title"]}).sort_values("낙찰일", ascending=False)
    st.dataframe(view, hide_index=True, width="stretch", height=420,
                 column_config={"낙찰금액(원)": st.column_config.NumberColumn(format="localized")})
    download_buttons(view, "awards")
with tabs[6]:
    show_failed()
