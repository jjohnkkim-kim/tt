"""공통 디자인: 전역 CSS, 페이지 헤더, 차트 테마, 칩/배지."""
from __future__ import annotations

from html import escape

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

FONT = "Pretendard, 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif"
# 검증된 범주형 팔레트(light) 앞 4칸 — 차트 색은 이 순서로만 사용
COLORWAY = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]

CSS = """
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.css');
:root{
  --hbr-ink:#162033; --hbr-ink-2:#4b5a73; --hbr-ink-3:#7a889f;
  --hbr-line:#e3e8f2; --hbr-card:#ffffff; --hbr-bg:#f4f6fb;
  --hbr-primary:#1f63c2; --hbr-primary-soft:#e6efff;
  --hbr-shadow:0 1px 2px rgba(22,32,51,.04), 0 6px 18px rgba(22,32,51,.05);
}
html, body, [class*="st-"], .stApp, button, input, textarea{
  font-family:'Pretendard Variable',Pretendard,'Apple SD Gothic Neo','Malgun Gothic',sans-serif !important;
  -webkit-font-smoothing:antialiased;
}
/* 아이콘 글꼴은 건드리지 않는다 */
[data-testid="stIconMaterial"], [data-testid="stExpanderIcon"], [data-testid="stIcon"], .material-symbols-rounded, span[class*="material"]{
  font-family:'Material Symbols Rounded' !important;
}
.stApp{background:var(--hbr-bg);}
[data-testid="stHeader"]{background:transparent;}
[data-testid="stDecoration"]{display:none;}
.block-container{padding-top:2.4rem !important; padding-bottom:4rem; max-width:1320px;}

/* 제목 */
h1{font-size:1.7rem !important; font-weight:700 !important; letter-spacing:-.02em; color:var(--hbr-ink); padding:0 !important;}
h2,h3{letter-spacing:-.015em; color:var(--hbr-ink); font-weight:650 !important;}
h3{font-size:1.15rem !important; margin-top:1.4rem;}
[data-testid="stCaptionContainer"]{color:var(--hbr-ink-3);}

/* 페이지 헤더 */
.hbr-head{display:flex; align-items:flex-end; justify-content:space-between; gap:16px; margin:0 0 1.2rem;}
.hbr-head .t{font-size:1.75rem; font-weight:700; letter-spacing:-.025em; color:var(--hbr-ink); line-height:1.15;}
.hbr-head .s{margin-top:.35rem; color:var(--hbr-ink-3); font-size:.92rem;}
.hbr-head .eyebrow{font-size:.72rem; font-weight:700; letter-spacing:.12em; text-transform:uppercase; color:var(--hbr-primary); margin-bottom:.35rem;}

/* KPI 카드 */
[data-testid="stMetric"]{
  background:var(--hbr-card); border:1px solid var(--hbr-line); border-radius:16px;
  padding:16px 18px 14px; box-shadow:var(--hbr-shadow);
}
[data-testid="stMetricLabel"] p{font-size:.78rem !important; font-weight:600; color:var(--hbr-ink-3) !important; letter-spacing:.01em;}
[data-testid="stMetricValue"]{font-size:1.65rem !important; font-weight:700 !important; letter-spacing:-.02em; color:var(--hbr-ink);}
[data-testid="stMetricDelta"]{font-size:.8rem;}

/* 카드형 컨테이너 / 표 / 차트 */
[data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"]){border-radius:16px;}
div[data-testid="stVerticalBlockBorderWrapper"]{background:var(--hbr-card); border-color:var(--hbr-line) !important; box-shadow:var(--hbr-shadow);}
[data-testid="stDataFrame"]{border:1px solid var(--hbr-line); border-radius:14px; overflow:hidden; box-shadow:var(--hbr-shadow); background:var(--hbr-card);}
[data-testid="stPlotlyChart"] .js-plotly-plot, [data-testid="stPlotlyChart"] .plot-container, [data-testid="stPlotlyChart"] .svg-container, [data-testid="stPlotlyChart"] .main-svg{background:transparent !important;}
[data-testid="stPlotlyChart"] .bg{fill:transparent !important;}
[data-testid="stPlotlyChart"]{background:var(--hbr-card); border:1px solid var(--hbr-line); border-radius:16px; padding:8px; box-shadow:var(--hbr-shadow);}
[data-testid="stExpander"]{background:var(--hbr-card); border:1px solid var(--hbr-line) !important; border-radius:14px; box-shadow:var(--hbr-shadow);}
[data-testid="stExpander"] summary{font-weight:600;}
[data-testid="stAlert"]{border-radius:12px;}

div[data-testid="stVerticalBlockBorderWrapper"] [data-testid="stMetric"]{box-shadow:none; background:#f6f8fc; border-color:#e9edf5; min-height:0;}
div[data-testid="stVerticalBlockBorderWrapper"] [data-testid="stMetricLabel"]{min-height:0;}

/* 입력 / 버튼 */
[data-baseweb="input"], [data-baseweb="select"] > div, [data-baseweb="textarea"]{border-radius:10px !important; background:#fff !important;}
.stButton > button, .stDownloadButton > button, [data-testid="stLinkButton"] a{
  border-radius:10px; font-weight:600; border:1px solid var(--hbr-line); transition:all .15s ease;
}
.stButton > button:hover, .stDownloadButton > button:hover{border-color:var(--hbr-primary); color:var(--hbr-primary); transform:translateY(-1px);}
.stButton > button[kind="primary"], [data-testid="stLinkButton"] a[kind="primary"], a[data-testid="stBaseLinkButton-primary"]{
  background:var(--hbr-primary); color:#fff; border-color:var(--hbr-primary);
}
.stButton > button[kind="primary"]:hover{color:#fff; filter:brightness(1.08);}
[data-baseweb="tab-list"]{gap:6px;}
[data-baseweb="tab"]{border-radius:10px 10px 0 0; font-weight:600;}

/* 사이드바 */
[data-testid="stSidebar"]{border-right:1px solid #1c2d52;}
[data-testid="stSidebar"] *{color:#d9e2f2;}
[data-testid="stSidebarNav"] a, [data-testid="stSidebarNavLink"]{border-radius:10px; padding:.5rem .7rem; margin:2px 0; font-weight:550; color:#c5d2ea !important;}
[data-testid="stSidebarNavLink"]:hover{background:#17274a !important;}
[data-testid="stSidebarNavLink"][aria-current="page"]{background:linear-gradient(90deg,#2458b8,#1f4a9a) !important; color:#fff !important; box-shadow:0 4px 14px rgba(20,60,140,.35);}
[data-testid="stSidebarNavLink"][aria-current="page"] *{color:#fff !important;}
[data-testid="stSidebar"] .stButton > button{background:#17274a; color:#e6eefc; border:1px solid #2a3f6e; width:100%;}
[data-testid="stSidebar"] .stButton > button:hover{background:#1f3562; border-color:#7fb0ff; color:#fff;}
[data-testid="stSidebar"] [data-testid="stExpander"]{background:#13213f; border:1px solid #243a68 !important; box-shadow:none;}
[data-testid="stSidebar"] [data-baseweb="input"]{background:#0f1b33 !important;}
[data-testid="stSidebar"] input{color:#fff !important;}
[data-testid="stSidebar"] hr{border-color:#22345c;}
[data-testid="stSidebar"] [data-testid="stAlert"]{background:#2a2410; border:1px solid #5b4a14;}

.hbr-brand2{padding:.35rem .2rem 1.1rem; margin-bottom:.9rem; border-bottom:1px solid #1f3159;}
.hbr-brand2 .row{display:flex; align-items:center; gap:14px;}
.hbr-brand2 .mk{flex:none; filter:drop-shadow(0 8px 18px rgba(37,99,235,.45));}
.hbr-brand2 .nm1{font-size:.8rem; font-weight:700; letter-spacing:.26em; text-transform:uppercase; color:#7fb0ff; line-height:1.2;}
.hbr-brand2 .nm2{font-size:1.72rem; font-weight:800; letter-spacing:-.03em; color:#fff; line-height:1.05; margin-top:.1rem;
  background:linear-gradient(180deg,#fff 30%,#c9dcff); -webkit-background-clip:text; background-clip:text; -webkit-text-fill-color:transparent;}
.hbr-brand2 .tg{margin-top:1rem; font-size:.7rem; font-weight:600; letter-spacing:.1em; color:#a4b8dc; text-transform:uppercase; white-space:nowrap;}
/* 사이드바 맨 위의 접기 버튼은 브랜드 위에 겹쳐 둔다 */
[data-testid="stSidebarHeader"]{position:absolute !important; top:.5rem; right:.3rem; padding:0 !important; height:auto !important; width:auto !important; background:transparent !important; z-index:20;}
[data-testid="stSidebarUserContent"]{padding-top:1.6rem !important;}
/* 사이드바 메뉴(page_link) */
[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"]{border-radius:12px; padding:.5rem .8rem; margin:2px 0; color:#c5d2ea !important; font-weight:600; transition:background .15s ease;}
[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"]:hover{background:#17274a;}
[data-testid="stSidebar"] [data-testid="stPageLink"]{margin:0;}
[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"] *{color:inherit !important;}
.hbr-user{display:flex; align-items:center; gap:10px; background:#13213f; border:1px solid #243a68; border-radius:12px; padding:.6rem .7rem; margin:.4rem 0 .8rem;}
.hbr-user .av{width:32px; height:32px; border-radius:50%; background:linear-gradient(135deg,#60a5fa,#14b8a6); display:grid; place-items:center; font-weight:700; color:#06122b !important;}
.hbr-user .nm{font-weight:600; font-size:.88rem; color:#fff !important; line-height:1.15;}
.hbr-user .rl{font-size:.7rem; color:#8ea3c7 !important; letter-spacing:.06em; text-transform:uppercase;}

/* 칩 */
.hbr-chip{display:inline-block; padding:.18rem .6rem; margin:0 .3rem .3rem 0; border-radius:999px; font-size:.76rem; font-weight:600;
  background:var(--hbr-primary-soft); color:#164fa0; border:1px solid #cfe0ff;}
.hbr-chip.warn{background:#fff4e0; color:#8a4b00; border-color:#ffe0ac;}
.hbr-chip.gray{background:#eef1f7; color:#4b5a73; border-color:#e0e5ef;}
.hbr-chip.ok{background:#e4f6ee; color:#0b6b46; border-color:#bfe9d6;}
.hbr-detail-title{font-size:1.2rem; font-weight:700; letter-spacing:-.015em; color:var(--hbr-ink); margin:.1rem 0 .5rem; line-height:1.35;}
.hbr-section{display:flex; align-items:center; gap:10px; margin:1.6rem 0 .6rem; font-weight:700; font-size:1.05rem; color:var(--hbr-ink); letter-spacing:-.01em;}
.hbr-section:before{content:""; width:4px; height:18px; border-radius:2px; background:var(--hbr-primary);}
[data-testid="stSidebarHeader"] img, [data-testid="stLogo"]{width:100% !important; height:auto !important; max-height:none !important;}
[data-testid="stSidebarHeader"]{display:flex !important; align-items:center; gap:.4rem;}
[data-testid="stSidebarHeader"] > *:has(img){flex:1 1 auto !important; min-width:0 !important; width:100% !important; max-width:none !important;}
[data-testid="stSidebarHeader"] > *:has(img) > *{width:100% !important; max-width:none !important;}
[data-testid="stSidebarHeader"] img{object-fit:contain; object-position:left center;}
[data-testid="stMetric"]{min-height:104px;}
[data-testid="stMetricLabel"]{min-height:2.5em;}
[data-testid="stSidebarHeader"]{padding:1.3rem 1rem .8rem;}
[data-testid="stMetricLabel"], [data-testid="stMetricLabel"] p, [data-testid="stMetricLabel"] div{white-space:normal !important; overflow:visible !important; text-overflow:clip !important; line-height:1.25;}
.hbr-action{display:flex; gap:10px; align-items:flex-start; padding:.55rem .75rem; margin:.3rem 0; border:1px solid var(--hbr-line); border-radius:12px; background:#fbfcfe; font-size:.92rem;}
.hbr-action .tag{flex:none; padding:.12rem .5rem; border-radius:999px; font-size:.7rem; font-weight:700; margin-top:.1rem;}
.hbr-action .tag.hi{background:#fde8e8; color:#a31515;} .hbr-action .tag.mid{background:#fff4e0; color:#8a4b00;} .hbr-action .tag.lo{background:#eef1f7; color:#4b5a73;}
.hbr-reasons{margin:.2rem 0 .8rem; padding-left:1.1rem; color:var(--hbr-ink-2);}
/* 폰 화면: 컬럼을 2개씩 나란히, 카드는 작게 */
@media (max-width: 640px){
  .block-container{padding-left:1rem !important; padding-right:1rem !important; padding-top:3.2rem !important;}
  [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]){flex-wrap:wrap !important; gap:.6rem !important;}
  [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) > [data-testid="stColumn"]{flex:1 1 calc(50% - .6rem) !important; min-width:calc(50% - .6rem) !important; width:auto !important;}
  [data-testid="stMetric"]{min-height:0; padding:12px 14px 10px; border-radius:14px;}
  [data-testid="stMetricValue"]{font-size:1.3rem !important;}
  [data-testid="stMetricLabel"], [data-testid="stMetricLabel"] p{font-size:.72rem !important; min-height:0;}
  .hbr-head .t{font-size:1.5rem;}
  .hbr-detail-title{font-size:1.05rem;}
}
/* 대시보드 공고 카드 */
.hbr-list{display:flex; flex-direction:column; gap:.55rem;}
.hbr-bid{background:var(--hbr-card); border:1px solid var(--hbr-line); border-radius:14px; padding:.8rem .95rem; box-shadow:var(--hbr-shadow);
  display:flex; justify-content:space-between; align-items:flex-start; gap:14px; transition:border-color .15s ease, transform .15s ease;}
.hbr-bid:hover{border-color:#b9cdf3; transform:translateY(-1px);}
.hbr-bid .ti{display:block; font-weight:650; color:var(--hbr-ink) !important; line-height:1.38; text-decoration:none !important; word-break:keep-all;}
.hbr-bid a.ti:hover{color:var(--hbr-primary) !important;}
.hbr-bid .me{font-size:.8rem; color:var(--hbr-ink-3); margin-top:.3rem; line-height:1.5;}
.hbr-bid .tg{margin-top:.35rem;}
.hbr-bid .tg .hbr-chip{margin-bottom:0; font-size:.7rem; padding:.1rem .5rem;}
.hbr-bid .rt{flex:none; text-align:right; min-width:3.4rem;}
.hbr-bid .rt .hbr-chip{margin:0;}
.hbr-bid .am{font-weight:700; font-size:.82rem; color:var(--hbr-ink-2); margin-top:.35rem; white-space:nowrap;}
.hbr-empty{color:var(--hbr-ink-3); border:1px dashed var(--hbr-line); border-radius:14px; padding:2rem 1rem; text-align:center; background:#fbfcfe; margin-top:2.2rem;}
#MainMenu, footer{visibility:hidden;} [data-testid="stAppDeployButton"]{display:none;}
</style>
"""

def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def _patch_plotly_chart() -> None:
    """plotly_chart: 이 코드베이스의 width="stretch" 를 현재 Streamlit 버전이 이해하도록 변환하고,
    Streamlit 기본 차트 테마 대신 아래 hbr 테마를 쓰게 한다. (한 번만 적용)"""
    from streamlit.delta_generator import DeltaGenerator

    if getattr(DeltaGenerator, "_hbr_patched", False):
        return
    orig = DeltaGenerator.plotly_chart

    def plotly_chart(self, figure_or_data, *args, **kwargs):
        if kwargs.pop("width", None) == "stretch":
            kwargs["use_container_width"] = True
        kwargs.setdefault("theme", None)
        return orig(self, figure_or_data, *args, **kwargs)

    DeltaGenerator.plotly_chart = plotly_chart
    DeltaGenerator._hbr_patched = True
    st.plotly_chart = st._main.plotly_chart     # st.plotly_chart 는 import 시점에 바인딩되어 있어 다시 연결


def apply_chart_theme() -> None:
    """모든 plotly 차트에 공통 테마(글꼴·색·격자) 적용."""
    _patch_plotly_chart()
    axis = dict(automargin=True, gridcolor="#e9edf5", zerolinecolor="#dfe5f0", linecolor="#dfe5f0", ticks="", tickfont=dict(color="#4b5a73"),
                title=dict(font=dict(color="#4b5a73")))
    pio.templates["hbr"] = go.layout.Template(layout=dict(
        font=dict(family=FONT, color="#162033", size=13), colorway=COLORWAY,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", xaxis=axis, yaxis=axis,
        legend=dict(font=dict(color="#4b5a73"), bgcolor="rgba(0,0,0,0)"),
        hoverlabel=dict(bgcolor="#0f1b33", font=dict(family=FONT, color="#fff"), bordercolor="#0f1b33"),
        margin=dict(l=16, r=16, t=36, b=16)))
    pio.templates.default = "hbr"


def highlight_page(url_path: str) -> None:
    """지금 열린 페이지의 메뉴를 강조 (page_link 는 현재 페이지 표시를 제공하지 않아 주소로 찾는다)."""
    href = escape(url_path or "", quote=True)
    st.markdown('<style>[data-testid="stSidebar"] a[data-testid="stPageLink-NavLink"][href="%s"]{background:linear-gradient(90deg,#2458b8,#1f4a9a) !important;'
                'color:#fff !important; box-shadow:0 6px 16px rgba(20,60,140,.38);}</style>' % href, unsafe_allow_html=True)


def sidebar_brand() -> None:
    from hbr import branding

    st.sidebar.markdown(
        f'<div class="hbr-brand2"><div class="row"><div class="mk">{branding.mark_svg(54, "s")}</div>'
        f'<div><div class="nm1">Hospital</div><div class="nm2">Bid Radar</div></div></div>'
        f'<div class="tg">Pharma · Bid Intelligence</div></div>', unsafe_allow_html=True)


def sidebar_user(name: str, role: str) -> None:
    initial = escape((name or "?").strip()[:1].upper() or "?")
    st.sidebar.markdown(f'<div class="hbr-user"><div class="av">{initial}</div><div><div class="nm">{escape(name or "-")}</div>'
                        f'<div class="rl">{escape(role or "")}</div></div></div>', unsafe_allow_html=True)


def page_header(title: str, subtitle: str | None = None, eyebrow: str | None = None) -> None:
    sub = f'<div class="s">{escape(subtitle)}</div>' if subtitle else ""
    eb = f'<div class="eyebrow">{escape(eyebrow)}</div>' if eyebrow else ""
    st.markdown(f'<div class="hbr-head"><div>{eb}<div class="t">{escape(title)}</div>{sub}</div></div>', unsafe_allow_html=True)


def section(title: str) -> None:
    st.markdown(f'<div class="hbr-section">{escape(title)}</div>', unsafe_allow_html=True)


def action_row(urgency: str, text: str) -> str:
    cls = "hi" if urgency == "긴급" else "mid" if urgency == "높음" else "lo"
    return f'<div class="hbr-action"><span class="tag {cls}">{escape(urgency)}</span><span>{escape(text)}</span></div>'


def bid_item(r, today, mode: str = "new") -> str:
    """대시보드의 공고 한 줄 카드. mode: new(등록일 표시) | closing(마감일 표시)."""
    import pandas as pd

    title = escape(str(r.get("title") or "-"))
    url = r.get("url")
    head = (f'<a class="ti" href="{escape(str(url), quote=True)}" target="_blank" rel="noopener">{title}</a>'
            if isinstance(url, str) and url.startswith("http") else f'<span class="ti">{title}</span>')
    tags = r.get("product_tags")
    tag_html = f'<div class="tg">{chips(tags)}</div>' if isinstance(tags, (list, tuple)) and tags else ""
    dl, bd = r.get("deadline"), r.get("bid_date")
    d = None if dl is None or pd.isna(dl) else (dl.normalize() - pd.Timestamp(today)).days
    when = ""
    if mode == "closing" and d is not None:
        when = f"마감 {dl:%m/%d %H:%M}"
    elif bd is not None and not pd.isna(bd):
        when = f"등록 {bd:%m/%d}" + (f" · 마감 {dl:%m/%d}" if d is not None else "")
    chip = ""
    if d is not None:
        tone = "warn" if 0 <= d <= 3 else "gray" if d < 0 else "ok"
        chip = chips([f"D-{d}" if d >= 0 else "마감"], tone)
    b = r.get("budget")
    amount = ""
    if b is not None and not pd.isna(b) and float(b) > 0:
        v = float(b)
        amount = f'<div class="am">{v / 1e8:,.2f}억</div>' if v >= 1e8 else f'<div class="am">{v / 1e4:,.0f}만원</div>'
    meta = " · ".join(x for x in (escape(str(r.get("hospital") or "")), when) if x)
    return f'<div class="hbr-bid"><div>{head}<div class="me">{meta}</div>{tag_html}</div><div class="rt">{chip}{amount}</div></div>'


def chips(labels, tone: str = "") -> str:
    return "".join(f'<span class="hbr-chip {tone}">{escape(str(t).strip())}</span>' for t in labels if str(t).strip())
