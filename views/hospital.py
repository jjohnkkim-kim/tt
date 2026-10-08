import pandas as pd
import plotly.express as px
import streamlit as st

from hbr.analytics.actions import recommend_actions
from hbr.analytics.data import pharma_only
from hbr.constants import SCORE_LABELS, SCORE_WEIGHTS
from hbr.utils import fmt_won

from views._common import date_str, opportunities, snapshot

st.title("🏥 병원 상세")
snap, opps = snapshot(), opportunities()
if snap.hospitals.empty:
    st.info("병원 데이터가 없습니다.")
    st.stop()

names = sorted(snap.hospitals["name"])
default = names.index(opps[0].hospital) if opps and opps[0].hospital in names else 0
name = st.selectbox("병원", names, index=default)
hrow = snap.hospitals[snap.hospitals["name"] == name].iloc[0]
hid = int(hrow["id"])
st.caption(f"{hrow.get('hospital_type') or '-'} · {hrow.get('region') or '지역 미분류'}")

o = next((x for x in opps if x.hospital_id == hid), None)
bids = pharma_only(snap.bids); bids = bids[bids["hospital_id"] == hid] if not bids.empty else bids
aw = pharma_only(snap.awards); aw = aw[aw["hospital_id"] == hid] if not aw.empty else aw
con = pharma_only(snap.contracts); con = con[con["hospital_id"] == hid] if not con.empty else con

c = st.columns(4)
c[0].metric("Opportunity Score", f"{o.score}점 · {o.grade}" if o else "-")
c[1].metric("계약종료", f"D-{o.days_to_expiry}" if o and o.days_to_expiry is not None and o.days_to_expiry >= 0 else "-",
            help=str(o.expiry_date) if o and o.expiry_date else None)
c[2].metric("예상 재입찰 시점", str(o.expected_rebid) if o and o.expected_rebid else "-",
            help="계약종료 45일 전 공고 가정(휴리스틱)")
c[3].metric("예상 기회금액", fmt_won(o.est_amount) if o else "-")

if o:
    left, right = st.columns(2)
    comp = pd.DataFrame({"항목": [f"{SCORE_LABELS[k]}" for k in SCORE_WEIGHTS], "점수": [o.components[k] for k in SCORE_WEIGHTS]})
    left.plotly_chart(px.bar(comp, x="점수", y="항목", orientation="h", range_x=[0, 100], height=260, text="점수"),
                      width="stretch")
    right.markdown("**근거**\n" + "\n".join(f"- {r}" for r in o.reasons))
    right.markdown("**🤖 추천 Action**\n" + "\n".join(f"- {a.text}" for a in recommend_actions(o)))

t1, t2, t3, t4 = st.tabs(["입찰 이력", "낙찰 이력", "계약 정보", "주요 공급사 / 경쟁사"])
with t1:
    if bids.empty: st.info("입찰 이력이 없습니다.")
    else:
        st.dataframe(pd.DataFrame({"공고일": date_str(bids["bid_date"]), "공고명": bids["title"], "예산(원)": bids["budget"],
                                   "마감": date_str(bids["deadline"], "%Y-%m-%d %H:%M"), "방식": bids["bid_method"]})
                     .sort_values("공고일", ascending=False), hide_index=True, width="stretch",
                     column_config={"예산(원)": st.column_config.NumberColumn(format="localized")})
with t2:
    if aw.empty: st.info("낙찰 이력이 없습니다.")
    else:
        st.dataframe(pd.DataFrame({"낙찰일": date_str(aw["award_date"]), "낙찰업체": aw["winner_name"], "경쟁사": aw["competitor"],
                                   "낙찰금액(원)": aw["award_amount"], "공고명": aw["title"]})
                     .sort_values("낙찰일", ascending=False), hide_index=True, width="stretch",
                     column_config={"낙찰금액(원)": st.column_config.NumberColumn(format="localized")})
with t3:
    if con.empty: st.info("계약 정보가 없습니다.")
    else:
        st.dataframe(pd.DataFrame({"계약업체": con["vendor_name"], "계약금액(원)": con["contract_amount"],
                                   "시작일": date_str(con["start_date"]), "종료일": date_str(con["end_date"]),
                                   "구분": con["end_date_estimated"].map({True: "추정", False: "확정"}), "계약명": con["title"]})
                     .sort_values("종료일", ascending=False), hide_index=True, width="stretch",
                     column_config={"계약금액(원)": st.column_config.NumberColumn(format="localized")})
with t4:
    if aw.empty and con.empty: st.info("공급사 정보가 없습니다.")
    else:
        src = pd.concat([aw.rename(columns={"winner_name": "vendor", "award_amount": "amount"})[["vendor", "amount", "competitor"]],
                         con.rename(columns={"vendor_name": "vendor", "contract_amount": "amount"})[["vendor", "amount", "competitor"]]])
        g = src.groupby("vendor")["amount"].sum().reset_index()
        g["억원"] = g["amount"] / 1e8
        st.plotly_chart(px.pie(g, names="vendor", values="억원", height=340, title="공급사 비중 (낙찰+계약 금액)"), width="stretch")
