import pandas as pd
import streamlit as st

from hbr.analytics.data import open_bids
from hbr.utils import today_kst

from views._common import current_user, date_str, download_buttons, empty_notice, repo, snapshot

st.title("📋 입찰공고 조회")
snap, today, user = snapshot(), today_kst(), current_user()
bids = snap.bids
if empty_notice(bids):
    st.stop()

with st.expander("🔎 검색 / 필터", expanded=True):
    c1, c2, c3 = st.columns([2, 2, 1])
    q = c1.text_input("공고명 · 기관명 검색", placeholder="예: 알부민")
    hosp = c2.multiselect("기관", sorted(bids["hospital"].dropna().unique()))
    status = c3.radio("상태", ["진행중", "마감", "전체"], horizontal=True)
    c4, c5, c6 = st.columns([1, 1, 2])
    pharma = c4.toggle("의약품 관련만", value=True)
    min_budget = c5.number_input("예산 하한 (억원)", min_value=0.0, value=0.0, step=0.5)
    sort = c6.selectbox("정렬", ["마감일 빠른순", "공고일 최신순", "예산 큰순"])

df = bids.copy()
if pharma:
    df = df[df["is_pharma"].fillna(False).astype(bool)]
if q:
    df = df[df["title"].str.contains(q, case=False, na=False) | df["hospital"].str.contains(q, case=False, na=False)]
if hosp:
    df = df[df["hospital"].isin(hosp)]
if status == "진행중":
    df = open_bids(df, today)
elif status == "마감":
    df = df[df["deadline"] < pd.Timestamp(today)]
if min_budget:
    df = df[df["budget"].fillna(0) >= min_budget * 1e8]
df = {"마감일 빠른순": df.sort_values("deadline"), "공고일 최신순": df.sort_values("bid_date", ascending=False),
      "예산 큰순": df.sort_values("budget", ascending=False)}[sort]

view = pd.DataFrame({
    "공고번호": df["bid_ntce_no"], "공고명": df["title"], "기관명": df["hospital"],
    "공고일": date_str(df["bid_date"]), "마감일": date_str(df["deadline"], "%Y-%m-%d %H:%M"),
    "D-day": (df["deadline"].dt.normalize() - pd.Timestamp(today)).dt.days,
    "예산금액(원)": df["budget"], "입찰방식": df["bid_method"], "나라장터": df["url"] if "url" in df else None})
st.caption(f"{len(view):,}건 · 행을 선택하면 아래에 상세가 열리고, '나라장터' 칸을 누르면 공고 원문이 새 탭으로 열립니다.")
event = st.dataframe(view, hide_index=True, width="stretch", height=440, on_select="rerun",
                     selection_mode="single-row", key="bids_table", column_config={
    "예산금액(원)": st.column_config.NumberColumn(format="%,d"),
    "D-day": st.column_config.NumberColumn(format="D-%d"),
    "나라장터": st.column_config.LinkColumn("나라장터", display_text="🔗 열기")})
rows = event.selection.rows if event and event.selection else []
if rows:
    r = view.iloc[rows[0]]
    with st.container(border=True):
        st.subheader(r["공고명"])
        a, b, c = st.columns(3)
        a.metric("기관", r["기관명"])
        b.metric("마감", r["마감일"], None if pd.isna(r["D-day"]) else f"D-{int(r['D-day'])}", delta_color="off")
        c.metric("예산", "-" if pd.isna(r["예산금액(원)"]) else f"{r['예산금액(원)'] / 1e8:,.2f}억원")
        st.caption(f"공고번호 {r['공고번호']} · 공고일 {r['공고일']} · 입찰방식 {r['입찰방식'] or '-'}")
        if isinstance(r["나라장터"], str) and r["나라장터"]:
            st.link_button("나라장터 공고 원문 열기 ↗", r["나라장터"], type="primary")
download_buttons(view, f"bids_{today}")

if user.can("watchlist") and user.id:
    st.divider()
    watched = repo().watched_hospital_ids(user.id)
    names = sorted(df["hospital"].dropna().unique())
    sel = st.multiselect("⭐ 관심기관 등록 (신규 입찰 즉시 알림)", names,
                         help="현재 필터 결과에 포함된 기관 중에서 선택")
    if st.button("관심기관 등록", disabled=not sel):
        ids = dict(zip(snap.hospitals["name"], snap.hospitals["id"]))
        added = sum(repo().add_watch(user.id, int(ids[n])) for n in sel)
        st.success(f"{added}개 기관을 등록했습니다.")
    if watched:
        st.caption("현재 관심기관: " + ", ".join(snap.hospital_name(h) for h in sorted(watched)))
