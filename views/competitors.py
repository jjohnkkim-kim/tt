from datetime import timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from hbr.analytics.competitors import coverage, hospital_share, prepare, vendor_detail, vendor_ranking
from hbr.analytics.data import pharma_only
from hbr.utils import fmt_won, today_kst

from views import _ui
from views._common import company_id, download_buttons, repo, snapshot

_ui.page_header("경쟁사 Radar", "실제 낙찰업체 기준으로 누가·어디서·얼마나 낙찰받는지", "COMPETITORS")
snap, today = snapshot(), today_kst()
own_aliases = repo().own_aliases(company_id())

f1, f2 = st.columns([3, 2])
days = f1.radio("분석 기간", [30, 90, 180, 365], index=1, horizontal=True, format_func=lambda d: f"최근 {d}일")
pharma = f2.toggle("의약품 관련만", value=True, help="끄면 모든 물품 낙찰을 분석합니다.")
raw = snap.awards if snap.awards is not None else pd.DataFrame()
raw = pharma_only(raw) if pharma and not raw.empty else raw
df = prepare(raw)
if df.empty:
    st.info("분석할 낙찰 데이터가 없습니다. 낙찰 수집이 켜져 있는지 확인해 주세요.")
    st.stop()

start, end = today - timedelta(days=days - 1), today
cov_s, cov_e = coverage(df)
have_days = (cov_e - cov_s).days + 1
st.caption(f"기준일 {today} · 보유한 낙찰 데이터 {cov_s} ~ {cov_e} ({have_days}일)" + (" · 내 회사(설정의 자사 표기명)는 '자사'로 표시" if own_aliases else ""))
if have_days < days:
    st.warning(f"보유한 낙찰 데이터가 {have_days}일치뿐이라, 최근 {days}일 분석은 이 기간만 반영됩니다. 데이터가 쌓일수록 정확해집니다.")

rk = vendor_ranking(df, start, end, own_aliases)
prev_start = start - timedelta(days=days)
prev_ok = cov_s <= prev_start                       # 직전 같은 길이 기간의 데이터가 있어야 증감을 말할 수 있다
t_rank, t_vendor, t_hosp = st.tabs(["업체 순위", "업체 상세", "병원별 점유율"])

with t_rank:
    if rk.empty:
        st.info("선택한 기간에 낙찰 실적이 없습니다.")
    else:
        c = st.columns(3)
        c[0].metric("낙찰 업체", f"{len(rk)}곳")
        c[1].metric("낙찰 건수", f"{int(rk['낙찰 건수'].sum()):,}건")
        c[2].metric("낙찰 금액", fmt_won(rk["낙찰 금액"].sum()))
        top = rk.head(10).iloc[::-1].assign(구분=lambda x: x["자사"].map({True: "자사", False: "경쟁사"}))
        fig = px.bar(top, x="낙찰 건수", y="업체", color="구분", orientation="h", text="낙찰 건수", height=max(280, 36 * len(top) + 80),
                     title=f"최근 {days}일 낙찰 건수 상위", color_discrete_map={"경쟁사": "#2a78d6", "자사": "#eb6834"})
        fig.update_layout(xaxis_title=None, yaxis_title=None, title_font_size=14, xaxis_visible=False, legend_title_text=None)
        fig.update_traces(marker_line_width=0, textposition="outside", cliponaxis=False)
        st.plotly_chart(fig, width="stretch")
        view = rk.drop(columns=["vendor_key"]).assign(
            순위=range(1, len(rk) + 1), **{"최근 낙찰일": rk["최근 낙찰일"].dt.strftime("%Y-%m-%d"), "자사": rk["자사"].map({True: "자사", False: ""}),
                                         "변화": rk["변화"].map(lambda v: (f"▲{v}" if v > 0 else f"▼{-v}" if v < 0 else "-") if prev_ok else "-")})
        st.caption("변화 = 직전 같은 길이 기간 대비 낙찰 건수 증감" if prev_ok else
                   f"변화: 직전 {days}일({prev_start} ~)의 데이터를 아직 보유하지 않아 계산하지 않았습니다 (데이터가 쌓이면 표시됩니다).")
        st.dataframe(view[["순위", "업체", "자사", "낙찰 건수", "변화", "낙찰 금액", "낙찰 병원 수", "최근 낙찰일"]], hide_index=True, width="stretch", height=420,
                     column_config={"낙찰 금액": st.column_config.NumberColumn(format="localized")})
        download_buttons(view.drop(columns=["직전 기간 건수"]), f"competitors_{days}d")

with t_vendor:
    if rk.empty:
        st.info("선택한 기간에 낙찰 실적이 없습니다.")
    else:
        label = {r.vendor_key: f"{r.업체}{' (자사)' if r.자사 else ''} · {r._2}건" for r in rk.rename(columns={"낙찰 건수": "_2"}).itertuples()}
        key = st.selectbox("업체", list(label), format_func=lambda k: label[k])
        d = vendor_detail(df, key, start, end)
        c = st.columns(3)
        c[0].metric("낙찰 건수", f"{d['total']}건")
        c[1].metric("낙찰 금액", fmt_won(d["amount"]))
        c[2].metric("낙찰 병원", f"{len(d['by_hospital'])}곳")
        g1, g2 = st.columns(2)
        with g1:
            fig = px.bar(d["monthly"], x="월", y="건수", height=280, title="월별 낙찰 건수")
            fig.update_layout(xaxis_title=None, yaxis_title=None, title_font_size=14, bargap=.4)
            st.plotly_chart(fig, width="stretch")
        with g2:
            _ui.section("주요 낙찰 병원")
            st.dataframe(d["by_hospital"].head(8).assign(최근=lambda x: x["최근"].dt.strftime("%Y-%m-%d")).rename(columns={"hospital": "병원"}),
                         hide_index=True, width="stretch", height=250, column_config={"금액": st.column_config.NumberColumn(format="localized")})
        if not d["tags"].empty:
            st.caption("낙찰 분류: " + " · ".join(f"{r.분류} {r.건수}건" for r in d["tags"].itertuples()))
        _ui.section("낙찰 이력")
        h = d["history"]
        hist = pd.DataFrame({"낙찰일": h["award_date"].dt.strftime("%Y-%m-%d"), "병원": h["hospital"], "공고명": h["title"], "금액(원)": h["award_amount"]})
        st.dataframe(hist, hide_index=True, width="stretch", height=320, column_config={"금액(원)": st.column_config.NumberColumn(format="localized")})

with t_hosp:
    win = df[(df["award_date"] >= pd.Timestamp(start)) & (df["award_date"] < pd.Timestamp(end) + pd.Timedelta(days=1))]
    if win.empty:
        st.info("선택한 기간에 낙찰 실적이 없습니다.")
    else:
        hcount = win.groupby(["hospital_id", "hospital"]).size().reset_index(name="n").sort_values("n", ascending=False)
        h1, h2 = st.columns([3, 1])
        hid = h1.selectbox("병원", hcount["hospital_id"].tolist(), format_func=lambda i: f"{hcount.loc[hcount['hospital_id'] == i, 'hospital'].iloc[0]} · {int(hcount.loc[hcount['hospital_id'] == i, 'n'].iloc[0])}건")
        by = h2.radio("기준", ["count", "amount"], horizontal=True, format_func=lambda b: "건수" if b == "count" else "금액")
        sh = hospital_share(df, hid, start, end, by)
        st.caption(f"최근 {days}일 {sh['basis']} 기준 · 낙찰 {sh['n']}건")
        if not sh["sufficient"]:
            st.warning(f"낙찰이 {sh['n']}건뿐이라 점유율은 참고용입니다 (5건 이상부터 의미가 커져요). 데이터 부족.")
        if sh["table"].empty:
            st.info("점유율을 계산할 수 있는 데이터가 없습니다.")
        else:
            t = sh["table"]
            fig = px.bar(t.iloc[::-1], x="비중(%)", y="업체", orientation="h", text="비중(%)", height=max(240, 38 * len(t) + 70))
            fig.update_layout(xaxis_title=None, yaxis_title=None, xaxis_visible=False)
            fig.update_traces(marker_line_width=0, texttemplate="%{text}%", textposition="outside", cliponaxis=False)
            st.plotly_chart(fig, width="stretch")
            st.dataframe(t, hide_index=True, width="stretch")
