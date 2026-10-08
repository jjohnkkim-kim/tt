import pandas as pd
import plotly.express as px
import streamlit as st

from hbr.analytics.metrics import expiring_contracts
from hbr.utils import today_kst

from views import _ui
from views._common import download_buttons, empty_notice, snapshot

_ui.page_header("계약정보", "계약 만료 일정과 월별 규모", "CONTRACTS")
snap, today = snapshot(), today_kst()
if empty_notice(snap.contracts):
    st.stop()

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
        "계약시작일": df["start_date"].dt.strftime("%Y-%m-%d"), "계약종료일": df["end_date"].dt.strftime("%Y-%m-%d"),
        "종료일": df["end_date_estimated"].map({True: "추정", False: "확정"})})
    st.dataframe(view, hide_index=True, width="stretch", height=420, column_config={
        "계약금액(원)": st.column_config.NumberColumn(format="localized"),
        "D-day": st.column_config.NumberColumn(format="D-%d")})
    download_buttons(view, f"contracts_expiring_{choice}")
    m = df.assign(월=df["end_date"].dt.strftime("%Y-%m")).groupby(["월", "competitor"])["contract_amount"].sum().reset_index()
    m["억원"] = m["contract_amount"] / 1e8
    st.plotly_chart(px.bar(m, x="월", y="억원", color="competitor", height=300, title="월별 종료 계약 규모 (현재 공급사 기준)"),
                    width="stretch")
st.caption("계약종료일이 API 에 없는 경우 계약일 + 12개월로 추정하며 '추정' 으로 표시합니다.")
