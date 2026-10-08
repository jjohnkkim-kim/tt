"""Hospital Bid Radar — Streamlit 진입점. 인증(Entra ID) → RBAC → 페이지 라우팅."""
import streamlit as st

st.set_page_config(page_title="Hospital Bid Radar", page_icon="📡", layout="wide")

from hbr.auth.session import require_user  # noqa: E402
from views import _ui  # noqa: E402
from views._common import refresh_button, repo  # noqa: E402

_ui.inject_css()
_ui.apply_chart_theme()

user = require_user(repo())
st.session_state["user"] = user

PAGES = [  # (feature, 파일, 제목, 아이콘)
    ("dashboard", "views/dashboard.py", "대시보드", ":material/space_dashboard:"),
    ("bids", "views/bids.py", "입찰공고", ":material/list_alt:"),
    ("awards", "views/awards.py", "낙찰정보", ":material/emoji_events:"),
    ("contracts", "views/contracts.py", "계약정보", ":material/assignment:"),
    ("hospital", "views/hospital.py", "병원 상세", ":material/local_hospital:"),
    ("competitors", "views/competitors.py", "경쟁사", ":material/flag:"),
    ("copilot", "views/copilot.py", "AI Copilot", ":material/smart_toy:"),
    ("settings", "views/settings.py", "설정", ":material/settings:"),
]
from hbr.config import bids_only  # noqa: E402

BIDS_ONLY_PAGES = {"dashboard", "bids", "hospital", "copilot", "settings"}   # 낙찰·계약·경쟁사 화면 제외
allowed = [st.Page(f, title=t, icon=i, default=(k == "dashboard")) for k, f, t, i in PAGES
           if (k == "settings" or user.can(k)) and (not bids_only() or k in BIDS_ONLY_PAGES)]
pg = st.navigation(allowed)

from hbr.config import get_settings  # noqa: E402

settings = get_settings()
with st.sidebar:
    _ui.sidebar_user(user.name, user.role)
    if not settings.auth_disabled:
        st.button("로그아웃", on_click=st.logout, width="stretch")
refresh_button()

from views import _subscribe  # noqa: E402

_subscribe.render(repo())
if not settings.use_supabase:
    st.sidebar.warning("데모 모드: 가상 데이터입니다. Supabase 를 연결하면 실제 데이터가 표시됩니다.")
pg.run()
