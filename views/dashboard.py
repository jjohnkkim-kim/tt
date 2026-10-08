from datetime import timedelta
from html import escape

import pandas as pd
import plotly.express as px
import streamlit as st

from hbr.analytics.matching import match_frame
from hbr.analytics.metrics import bid_overview
from hbr.analytics.overview import build_overview, closing_bucket
from hbr.config import bids_only
from hbr.utils import today_kst

from views import _ui
from views._common import lifecycle, matches, my_products, snapshot

_ui.page_header("대시보드", "오늘 확인할 입찰·낙찰·계약 소식을 한눈에", "TODAY")
snap, today = snapshot(), today_kst()
lc, mt, products = lifecycle(), matches(), my_products()
show_results = not bids_only()            # 낙찰·계약까지 수집하는 경우에만 결과 관련 숫자·구역을 보여준다

# ── 기간 / 범위 ─────────────────────────────────────────────────
f1, f2, f3 = st.columns([3, 2, 2])
period = f1.radio("기간", ["오늘", "최근 7일", "최근 30일", "사용자 지정"], index=1, horizontal=True)
pharma = f3.toggle("의약품 관련만", value=True, help="끄면 의료기기·소모품 등 모든 병원 입찰공고를 봅니다.")
if period == "사용자 지정":
    picked = f2.date_input("기간 선택", value=(today - timedelta(days=13), today), max_value=today)
    start, end = (picked if isinstance(picked, (tuple, list)) and len(picked) == 2 else (today - timedelta(days=13), today))
else:
    start = today - timedelta(days={"오늘": 0, "최근 7일": 6, "최근 30일": 29}[period])
    end = today
st.caption(f"기준일 {today} · 선택 기간 {start} ~ {end}" + (" · 낙찰·유찰은 개찰 며칠 뒤 공개되어 최근 기간은 비어 있을 수 있어요" if show_results else ""))

ov = build_overview(snap, lc, mt, today, start, end, pharma=pharma, has_products=bool(products))
k = ov["kpi"]
scope = "의약품" if pharma else "전체"

c = st.columns(4)
c[0].metric(f"신규 {scope} 입찰", f"{k['new']}건", help="선택 기간에 등록된 공고 수")
c[1].metric("내 관심제품 관련", f"{k['related']}건" if products else "—",
            help="선택 기간의 신규 공고 중 내 관심 제품과 매칭 신뢰도 MEDIUM 이상인 건수입니다." if products
            else "설정 → 회사·관심제품에서 관심 제품을 등록하면 자동으로 매칭합니다.")
c[2].metric("마감 임박 (7일 이내)", f"{k['closing']}건", help="기간과 상관없이 지금부터 7일 안에 마감되는 진행중 공고")
c[3].metric("재공고", f"{k['rebid']}건", help="선택 기간에 등록된 공고 중 재공고·재입찰·확대공고 표시가 있는 건수")
if show_results:
    c2 = st.columns(4)
    c2[0].metric("낙찰 결과", f"{k['awarded']}건", help="선택 기간에 개찰되어 낙찰자가 정해진 공고 수")
    c2[1].metric("유찰", f"{k['failed']}건", help="낙찰자 없이 끝난 공고 수. 이후 재공고가 나올 수 있습니다.")
    c2[2].metric("계약 종료 임박 (90일)", f"{k['expiring']}건", help="종료일 정보가 있는 의약품 계약만 집계합니다.")
    c2[3].metric("경쟁사 신규 수주", f"{k['competitor_awards']}건", help="선택 기간 낙찰 중 내 회사(설정의 자사 표기명)가 아닌 업체의 건수")

LIMIT = 5


def cards(df: pd.DataFrame, render) -> None:
    if df is None or df.empty:
        st.caption("해당하는 항목이 없습니다.")
        return
    st.markdown('<div class="hbr-list">' + "".join(render(r) for _, r in df.head(LIMIT).iterrows()) + "</div>", unsafe_allow_html=True)
    if len(df) > LIMIT:
        st.caption(f"외 {len(df) - LIMIT}건")


def match_chip(idx) -> str:
    m = mt.loc[idx] if idx in mt.index else None
    if m is None or pd.isna(m.get("match_product")):
        return ""
    tone = {"HIGH": "ok", "MEDIUM": "", "LOW": "warn"}[m["match_level"]]
    review = " · 검토 필요" if m["match_level"] == "LOW" else ""
    label = "내 제품 %s · %s %d%%%s" % (m["match_product"], m["match_level"], int(m["match_score"]), review)
    return '<div class="tg">' + _ui.chips([label], tone) + "</div>"


# ── ① 마감 임박 ─────────────────────────────────────────────────
_ui.section(f"마감 임박 {k['closing']}건")
if ov["closing"].empty:
    st.caption("7일 안에 마감되는 진행중 공고가 없습니다.")
else:
    counts = {d: len(closing_bucket(ov["closing"], today, d)) for d in (1, 3, 7)}
    tabs = st.tabs([f"D-{d} 이내 ({counts[d]})" for d in (1, 3, 7)])         # 건수를 제목에 넣어 비어 있는 탭을 한눈에 알 수 있게
    for tab, days in zip(tabs, (1, 3, 7)):
        with tab:
            cards(closing_bucket(ov["closing"], today, days),
                  lambda r: _ui.bid_item(r, today, "closing", extra=match_chip(r.name)))

# ── ② 내 관심제품 신규 입찰 / ③ 최근 낙찰 ────────────────────────
left, right = st.columns(2)
with left:
    _ui.section(f"내 관심제품 신규 입찰 {k['related']}건" if products else "내 관심제품 신규 입찰")
    if not products:
        st.markdown('<div class="hbr-empty" style="margin-top:.4rem">관심 제품을 등록하면<br>나와 관련된 신규 입찰이 여기에 모여요.</div>', unsafe_allow_html=True)
        try:
            st.page_link("views/settings.py", label="관심 제품 등록하기", icon=":material/arrow_forward:")
        except Exception:   # noqa: BLE001 — 이 화면만 단독 실행(테스트)될 때는 페이지 목록이 없다
            pass
    else:
        cards(ov["related"], lambda r: _ui.bid_item(r, today, "new", extra=match_chip(r.name)))
        if k["review"]:
            st.caption(f"신뢰도가 낮아 '검토 필요'인 매칭 {k['review']}건은 입찰공고 화면에서 확인할 수 있어요.")
with right:
    if show_results:
        _ui.section(f"최근 낙찰 {k['awarded']}건")
        aw = ov["awarded"]
        am = match_frame(aw.head(LIMIT), products) if products and not aw.empty else None
        def award_card(r):
            extra = ""
            if am is not None and r.name in am.index and pd.notna(am.loc[r.name, "match_product"]):
                extra = '<div style="margin:-.35rem 0 .55rem .2rem">' + _ui.chips(["내 제품 " + str(am.loc[r.name, "match_product"])], "ok") + "</div>"
            return _ui.result_item(r, "낙찰") + extra

        cards(aw, award_card)
    else:
        _ui.section("최근 낙찰")
        st.caption("낙찰 수집이 꺼져 있습니다.")

# ── ④ 유찰 / 재공고 ─────────────────────────────────────────────
left, right = st.columns(2)
with left:
    _ui.section(f"유찰 {k['failed']}건" if show_results else "유찰")
    if show_results:
        cards(ov["failed"], lambda r: _ui.result_item(r, "유찰"))
    else:
        st.caption("낙찰 수집이 꺼져 있습니다.")
with right:
    _ui.section(f"재공고 {k['rebid']}건")

    def rebid_card(r):
        li = ov["lc_new"].loc[r.name] if r.name in ov["lc_new"].index else None
        note = ""
        if li is not None and pd.notna(li.get("prev_ntce_no")):
            note = f"↩ 이전 {li['prev_status']} {pd.Timestamp(li['prev_date']):%m/%d} (추정 연결)"
        return _ui.bid_item(r, today, "new", extra=match_chip(r.name), note=note)

    cards(ov["rebids"], rebid_card)

# ── ⑤ 계약 종료 임박 ────────────────────────────────────────────
if show_results:
    _ui.section(f"계약 종료 임박 {k['expiring']}건")
    if ov["expiring"].empty:
        st.markdown(f'<div class="hbr-empty" style="margin-top:.2rem">종료일이 알려진 계약 중 90일 안에 끝나는 계약이 없습니다.<br>'
                    f'<span style="font-size:.82rem">의약품 계약 {ov["contracts_total"]}건 중 종료일 정보가 있는 건 {ov["contracts_with_end"]}건이에요. '
                    f'나라장터가 계약기간을 주지 않는 계약은 종료일을 추정해서 채우지 않습니다.</span></div>', unsafe_allow_html=True)
    else:
        cards(ov["expiring"], lambda r: _ui.contract_item(r, today))

# ── 공고 현황 (차트) ────────────────────────────────────────────
ovc = bid_overview(snap.bids, today, pharma=pharma)
_ui.section("공고 현황")
g1, g2 = st.columns([3, 2])
with g1:
    fig = px.bar(ovc["trend"], x="날짜", y="건수", height=300, title="최근 30일 공고 등록 추이")
    fig.update_layout(xaxis_title=None, yaxis_title=None, bargap=.35, title_font_size=14)
    fig.update_traces(marker_line_width=0, hovertemplate="%{x|%m/%d} · %{y}건<extra></extra>")
    st.plotly_chart(fig, width="stretch")
with g2:
    if ovc["tags"].empty:
        st.markdown('<div class="hbr-empty">의약품 분류가 있는 진행중 공고가 없습니다.</div>', unsafe_allow_html=True)
    else:
        t = ovc["tags"].sort_values("건수")
        fig = px.bar(t, x="건수", y="분류", orientation="h", height=300, text="건수", title="진행중 공고의 의약품 분류")
        fig.update_layout(xaxis_title=None, yaxis_title=None, title_font_size=14, xaxis_visible=False)
        fig.update_traces(marker_line_width=0, textposition="outside", cliponaxis=False)
        st.plotly_chart(fig, width="stretch")
if not ovc["hospitals"].empty:
    h = ovc["hospitals"].sort_values("건수")
    fig = px.bar(h, x="건수", y="기관", orientation="h", height=max(240, 38 * len(h) + 70), text="건수", title="진행중 공고가 많은 기관")
    fig.update_layout(xaxis_title=None, yaxis_title=None, title_font_size=14, xaxis_visible=False)
    fig.update_traces(marker_line_width=0, textposition="outside", cliponaxis=False)
    st.plotly_chart(fig, width="stretch")

try:
    st.page_link("views/bids.py", label="전체 입찰공고 보기", icon=":material/arrow_forward:")
except Exception:   # noqa: BLE001
    pass
