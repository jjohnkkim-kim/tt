import pandas as pd
import plotly.express as px
import streamlit as st

from hbr.analytics.data import pharma_only
from hbr.analytics.metrics import share_by_year
from hbr.utils import fmt_won, today_kst

from views._common import snapshot

st.title("🎯 경쟁사 Intelligence")
snap = snapshot()
aw = pharma_only(snap.awards)
if aw.empty:
    st.info("낙찰 데이터가 없습니다.")
    st.stop()

aw = aw.join(snap.hospitals.set_index("id")[["region"]], on="hospital_id")
names = [n for n in sorted(aw["competitor"].unique())]
sel = st.multiselect("분석 대상", names, default=[n for n in names if n != "기타"] or names)
df = aw[aw["competitor"].isin(sel)]
if df.empty:
    st.info("선택한 업체의 수주 실적이 없습니다.")
    st.stop()

today = pd.Timestamp(today_kst())
recent = df[df["award_date"] >= today - pd.Timedelta(days=90)]
c = st.columns(3)
c[0].metric("최근 90일 수주", f"{len(recent)}건")
c[1].metric("최근 90일 금액", fmt_won(recent["award_amount"].sum()))
c[2].metric("전체 누적", fmt_won(df["award_amount"].sum()))

t = st.tabs(["최근 수주실적", "병원별", "지역별", "연도별 추이", "점유율 변화"])
with t[0]:
    st.dataframe(pd.DataFrame({"일자": df["award_date"].dt.strftime("%Y-%m-%d"), "경쟁사": df["competitor"], "병원": df["hospital"],
                               "금액(원)": df["award_amount"], "공고명": df["title"]}).sort_values("일자", ascending=False).head(100),
                 hide_index=True, width="stretch", column_config={"금액(원)": st.column_config.NumberColumn(format="localized")})
with t[1]:
    g = df.groupby(["hospital", "competitor"]).agg(건수=("award_key", "count"), 금액=("award_amount", "sum")).reset_index()
    pv = g.pivot_table(index="hospital", columns="competitor", values="건수", fill_value=0)
    st.dataframe(pv.assign(합계=pv.sum(axis=1)).sort_values("합계", ascending=False), width="stretch")
with t[2]:
    g = df.assign(region=df["region"].fillna("미분류")).groupby(["region", "competitor"])["award_amount"].sum().reset_index()
    g["억원"] = g["award_amount"] / 1e8
    st.plotly_chart(px.bar(g, x="region", y="억원", color="competitor", height=360), width="stretch")
with t[3]:
    g = df.assign(year=df["award_date"].dt.year).groupby(["year", "competitor"])["award_amount"].sum().reset_index()
    g["억원"] = g["award_amount"] / 1e8
    st.plotly_chart(px.line(g, x="year", y="억원", color="competitor", markers=True, height=360), width="stretch")
with t[4]:
    sh = share_by_year(snap)
    sh["share"] = (sh["share"].astype(float) * 100).round(1)
    st.plotly_chart(px.bar(sh, x="year", y="share", color="competitor", height=360, labels={"share": "점유율(%)"}), width="stretch")
