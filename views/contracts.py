import pandas as pd
import plotly.express as px
import streamlit as st

from hbr.analytics.data import pharma_only
from hbr.analytics.metrics import expiring_contracts
from hbr.utils import today_kst

from views import _ui
from views._common import download_buttons, empty_notice, snapshot

_ui.page_header("계약정보", "계약 내역과 만료 일정", "CONTRACTS")
snap, today = snapshot(), today_kst()
if empty_notice(snap.contracts):
    st.stop()

con_all = pharma_only(snap.contracts)
t_list, t_end = st.tabs(["계약 내역", "종료 임박"])

with t_list:
    if con_all.empty:
        st.info("의약품 계약이 없습니다.")
    else:
        c = con_all.sort_values("contract_date", ascending=False)
        q = st.text_input("검색 (병원·계약명·업체)", key="con_q", placeholder="예: 알부민")
        if q:
            m = (c["title"].str.contains(q, case=False, na=False) | c["hospital"].str.contains(q, case=False, na=False)
                 | c["vendor_name"].str.contains(q, case=False, na=False))
            c = c[m]
        st.caption(f"{len(c):,}건 · 계약종료일은 나라장터가 제공하는 계약에만 표시하고, 없으면 '정보 없음'입니다.")
        lst = pd.DataFrame({
            "계약일": c["contract_date"].dt.strftime("%Y-%m-%d"), "병원": c["hospital"], "계약명": c["title"],
            "계약업체": c["vendor_name"], "경쟁사": c["competitor"], "계약금액(원)": c["contract_amount"],
            "계약종료일": c["end_date"].dt.strftime("%Y-%m-%d").fillna("정보 없음"), "입찰공고번호": c["raw"].map(
                lambda r: (r or {}).get("bidNtceNo") if isinstance(r, dict) else None)})
        st.dataframe(lst, hide_index=True, width="stretch", height=460,
                     column_config={"계약금액(원)": st.column_config.NumberColumn(format="localized")})
        download_buttons(lst, "contracts")

with t_end:
    choice = st.radio("계약만료 구간", ["D-7", "D-30", "D-60", "D-90", "D-180"], index=3, horizontal=True)
    days = int(choice[2:])
    df = expiring_contracts(snap, today, days)

    c1, c2, c3 = st.columns(3)
    c1.metric(f"{choice} 이내 종료", f"{len(df)}건")
    c2.metric("대상 병원", f"{df['hospital_id'].nunique() if not df.empty else 0}곳")
    c3.metric("계약금액 합계", f"{(df['contract_amount'].sum() / 1e8 if not df.empty else 0):,.1f}억원")

    if df.empty:
        st.success("해당 구간에 종료 예정인 의약품 계약이 없습니다.")
    else:
        view = pd.DataFrame({
            "D-day": df["d_day"], "병원": df["hospital"], "계약명": df["title"], "계약업체": df["vendor_name"],
            "경쟁사": df["competitor"], "계약금액(원)": df["contract_amount"],
            "계약시작일": df["start_date"].dt.strftime("%Y-%m-%d").fillna("정보 없음"),
            "계약종료일": df["end_date"].dt.strftime("%Y-%m-%d").fillna("정보 없음")})
        st.dataframe(view, hide_index=True, width="stretch", height=420, column_config={
            "계약금액(원)": st.column_config.NumberColumn(format="localized"),
            "D-day": st.column_config.NumberColumn(format="D-%d")})
        download_buttons(view, f"contracts_expiring_{choice}")
        m = df.assign(월=df["end_date"].dt.strftime("%Y-%m")).groupby(["월", "competitor"])["contract_amount"].sum().reset_index()
        m["억원"] = m["contract_amount"] / 1e8
        st.plotly_chart(px.bar(m, x="월", y="억원", color="competitor", height=300, title="월별 종료 계약 규모 (현재 공급사 기준)"),
                        width="stretch")

_con = pharma_only(snap.contracts)
_with_end = int(_con["end_date"].notna().sum()) if not _con.empty and "end_date" in _con else 0
st.caption(f"계약종료일은 나라장터가 제공하는 경우에만 표시합니다 (의약품 계약 {len(_con)}건 중 {_with_end}건에 종료일 정보). "
           "정보가 없는 계약은 만료 일정에 포함되지 않으며 종료일을 추정해서 채우지 않습니다.")
