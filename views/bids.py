from html import escape

import pandas as pd
import streamlit as st

from hbr.ai.bid_summary import build_facts, summarize
from hbr.analytics.data import open_bids
from hbr.utils import today_kst

from views import _ui
from hbr.analytics.lifecycle import STATUSES
from views._common import current_user, date_str, download_buttons, empty_notice, lifecycle, matches, my_products, repo, snapshot

@st.cache_data(ttl=86400, show_spinner=False)
def summarize_cached(facts: dict):
    """같은 공고 정보면 하루 동안 결과를 재사용 (AI 호출 비용 절감)."""
    return summarize(facts)


_ui.page_header("입찰공고", "병원 입찰공고를 검색하고 나라장터 원문으로 바로 이동", "BIDS")
snap, today, user = snapshot(), today_kst(), current_user()
bids = snap.bids
if empty_notice(bids):
    st.stop()
lc = lifecycle()
mt = matches()
products = my_products()

with st.expander("검색 / 필터", expanded=True, icon=":material/tune:"):
    c1, c2, c3 = st.columns([2, 2, 1])
    q = c1.text_input("공고명 · 기관명 검색", placeholder="예: 알부민")
    hosp = c2.multiselect("기관", sorted(bids["hospital"].dropna().unique()))
    status = c3.radio("상태", ["진행중", "마감", "전체"], horizontal=True)
    c4, c5, c6 = st.columns([1, 1, 2])
    pharma = c4.toggle("의약품 관련만", value=True)
    min_budget = c5.number_input("예산 하한 (억원)", min_value=0.0, value=0.0, step=0.5)
    sort = c6.selectbox("정렬", ["마감일 빠른순", "공고일 최신순", "예산 큰순"])
    if products:
        m1, m2 = st.columns([1, 2])
        mine_only = m1.toggle("내 관심제품 관련만", value=False, help=f"설정에 등록한 관심 제품 {len(products)}개와 매칭된 공고만 봅니다.")
        min_level = m2.selectbox("최소 매칭 신뢰도", ["LOW 이상 (검토 필요 포함)", "MEDIUM 이상", "HIGH만"], index=1, disabled=not mine_only)
    else:
        mine_only, min_level = False, ""
        st.caption("💡 설정 → 회사·관심제품에서 관심 제품을 등록하면 입찰공고와 자동으로 매칭해 드립니다.")
    stages = st.multiselect("진행 단계", STATUSES, placeholder="전체 (신규·진행중·낙찰·유찰·재공고·계약완료 …)",
                            help="공고 → 개찰 → 낙찰/유찰 → 계약 중 지금 어디까지 왔는지입니다. 공고번호가 같은 낙찰·계약 정보와 연결해 계산합니다.")

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
if stages:
    df = df[lc.reindex(df.index)["status"].isin(stages)]
if mine_only:
    floor = {"L": 35, "M": 55, "H": 80}[min_level[0]]
    df = df[mt.reindex(df.index)["match_score"].fillna(0) >= floor]
df = {"마감일 빠른순": df.sort_values("deadline"), "공고일 최신순": df.sort_values("bid_date", ascending=False),
      "예산 큰순": df.sort_values("budget", ascending=False)}[sort]

def tag_text(v) -> str:
    return ", ".join(v) if isinstance(v, (list, tuple)) or hasattr(v, "tolist") and not isinstance(v, str) else (v or "")


view = pd.DataFrame({      # 폰에서도 중요한 것(공고명·단계·기관·마감)이 먼저 보이도록 이 순서로 둔다
    "공고명": df["title"], "단계": lc.reindex(df.index)["status"].fillna("-"),
    "관심제품": mt.reindex(df.index).apply(lambda r: "" if pd.isna(r["match_product"]) else f"{r['match_product']} · {r['match_level']} {int(r['match_score'])}%"
                                           + (" (검토 필요)" if r["match_level"] == "LOW" else ""), axis=1) if products else "",
    "의약품 분류": df["product_tags"].map(tag_text) if "product_tags" in df else "",
    "기관명": df["hospital"], "마감일": date_str(df["deadline"], "%Y-%m-%d %H:%M"),
    "D-day": (df["deadline"].dt.normalize() - pd.Timestamp(today)).dt.days.map(
        lambda d: "" if pd.isna(d) else (f"D-{int(d)}" if d >= 0 else f"D+{int(-d)}")),         # D-5 = 5일 남음, D+30 = 30일 지남
    "예산금액(원)": df["budget"], "공고일": date_str(df["bid_date"]), "공고번호": df["bid_ntce_no"],
    "입찰방식": df["bid_method"], "나라장터": df["url"] if "url" in df else None})
st.caption(f"{len(view):,}건 · 행을 선택하면 아래에 상세가 열리고, '나라장터' 칸을 누르면 공고 원문이 새 탭으로 열립니다.")
event = st.dataframe(view, hide_index=True, width="stretch", height=440, on_select="rerun",
                     selection_mode="single-row", key="bids_table", column_config={
    "예산금액(원)": st.column_config.NumberColumn(format="localized"),
    "나라장터": st.column_config.LinkColumn("나라장터", display_text="🔗 열기")})
rows = event.selection.rows if event and event.selection else []
if rows:
    r = view.iloc[rows[0]]
    with st.container(border=True):
        st.markdown(f'<div class="hbr-detail-title">{escape(str(r["공고명"]))}</div>', unsafe_allow_html=True)
        tags = [t for t in str(r["의약품 분류"] or "").split(",") if t.strip()]
        _dd = (df["deadline"].dt.normalize() - pd.Timestamp(today)).dt.days.iloc[rows[0]]
        dday = None if pd.isna(_dd) else int(_dd)
        tone = "warn" if dday is not None and 0 <= dday <= 3 else "gray" if dday is not None and dday < 0 else "ok"
        status = "" if dday is None else _ui.chips([f"D-{dday}" if dday >= 0 else "마감"], tone)
        st.markdown(_ui.chips(tags) + status, unsafe_allow_html=True)
        a, b, c = st.columns(3)
        a.metric("기관", r["기관명"])
        b.metric("마감", r["마감일"])
        c.metric("예산", "-" if pd.isna(r["예산금액(원)"]) else f"{r['예산금액(원)'] / 1e8:,.2f}억원")
        st.caption(f"공고번호 {r['공고번호']} · 공고일 {r['공고일']} · 입찰방식 {r['입찰방식'] or '-'}")
        ms = mt.loc[df.index[rows[0]], "matches"] if products and df.index[rows[0]] in mt.index else []
        if ms:
            st.markdown("**내 관심제품 매칭** · 추정 신뢰도입니다 (공고 제목 기준)")
            for m in ms[:5]:
                tone = {"HIGH": "ok", "MEDIUM": "", "LOW": "warn"}[m.level]
                st.markdown(_ui.chips([f"{m.product} · {m.level} {m.score}%"], tone) + (" <b>검토 필요</b>" if m.needs_review else "")
                            + f"<br><span style='color:#7a889f;font-size:.82rem'>{escape(' · '.join(m.reasons))}</span>", unsafe_allow_html=True)
        li = lc.loc[df.index[rows[0]]] if df.index[rows[0]] in lc.index else None
        if li is not None:
            st.markdown("**진행 흐름** · " + _ui.chips([li["status"]], _ui.STATUS_TONE.get(li["status"], "")), unsafe_allow_html=True)
            b0 = df.iloc[rows[0]]
            money = lambda v: "" if v is None or pd.isna(v) or float(v) <= 0 else (f"{float(v) / 1e8:,.2f}억원" if float(v) >= 1e8 else f"{float(v) / 1e4:,.0f}만원")
            fmt = lambda d: "" if d is None or pd.isna(d) else pd.Timestamp(d).strftime("%Y-%m-%d")
            od = b0.get("open_date")
            res_state = {"낙찰": "done", "유찰": "fail"}.get(li["result_status"], "pending" if pd.isna(li["result_status"]) else "none")
            res_detail = (" · ".join(x for x in (str(li["winner_name"] or ""), money(li["award_amount"]), f"투찰 {int(li['bidder_count'])}곳" if pd.notna(li["bidder_count"]) else "") if x)
                          if li["result_status"] == "낙찰" else "낙찰자 없음" if li["result_status"] == "유찰" else "연결된 결과 없음 (개찰 전이거나 아직 미수집)")
            steps = [
                {"label": "공고", "date": fmt(b0.get("bid_date")), "detail": ("예산 " + money(b0.get("budget"))) if money(b0.get("budget")) else "", "state": "done"},
                {"label": "개찰", "date": fmt(od), "detail": "" if pd.notna(od) else "개찰일 정보 없음",
                 "state": "done" if pd.notna(od) and pd.Timestamp(od).normalize() <= pd.Timestamp(today) else "pending"},
                {"label": li["result_status"] if pd.notna(li["result_status"]) else "결과", "date": fmt(li["result_date"]), "detail": res_detail, "state": res_state},
                {"label": "계약", "date": fmt(li["contract_date"]), "state": "done" if pd.notna(li["contract_count"]) else "none",
                 "detail": (" · ".join(x for x in (str(li["contract_vendor"] or ""), money(li["contract_amount"])) if x)
                            if pd.notna(li["contract_count"]) else "연결된 계약 정보 없음"),
                 },
            ]
            note = ""
            if pd.notna(li["prev_ntce_no"]):
                note = (f"↩ <b>이전 {escape(str(li['prev_status']))}</b> {fmt(li['prev_date'])} · {escape(str(li['prev_title'])[:60])}"
                        f"<br><span style='opacity:.8'>{escape(str(li['prev_basis']))} — 같은 병원의 제목이 같거나 매우 비슷한 건을 추정해 연결한 것이며 확정이 아닙니다.</span>")
            st.markdown(_ui.lifecycle_flow(steps, note), unsafe_allow_html=True)
        b1 = df.iloc[rows[0]]
        li1 = lc.loc[df.index[rows[0]]] if df.index[rows[0]] in lc.index else None
        facts = build_facts(b1, today, None if li1 is None else li1["status"], ms,
                            None if li1 is None or pd.isna(li1["prev_ntce_no"]) else f"{li1['prev_status']} {str(li1['prev_title'])[:50]}")
        if st.button("공고 요약 보기", icon=":material/auto_awesome:", key=f"sum_{b1['bid_ntce_no']}"):
            with st.spinner("요약하는 중…"):
                text, src = summarize_cached(facts)
            st.markdown(text)
            st.caption(("AI가 위 공고 정보(제목·기관·예산·마감 등)만 보고 쓴 요약입니다. 첨부 내역은 포함되지 않아요." if src == "AI"
                        else "규칙으로 만든 요약입니다 (AI 키가 없거나 AI 호출이 실패하면 이렇게 보여요)."))
        if isinstance(r["나라장터"], str) and r["나라장터"]:
            st.link_button("나라장터 공고 원문 열기 ↗", r["나라장터"], type="primary")
download_buttons(view, f"bids_{today}")

if user.can("watchlist") and user.id:
    st.divider()
    watched = repo().watched_hospital_ids(user.id)
    names = sorted(df["hospital"].dropna().unique())
    sel = st.multiselect("관심기관 등록 (신규 입찰 즉시 알림)", names,
                         help="현재 필터 결과에 포함된 기관 중에서 선택")
    if st.button("관심기관 등록", disabled=not sel):
        ids = dict(zip(snap.hospitals["name"], snap.hospitals["id"]))
        added = sum(repo().add_watch(user.id, int(ids[n])) for n in sel)
        st.success(f"{added}개 기관을 등록했습니다.")
    if watched:
        st.caption("현재 관심기관: " + ", ".join(snap.hospital_name(h) for h in sorted(watched)))
