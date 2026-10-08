"""Hospital Bid Radar — Streamlit 진입점. 인증(Entra ID) → RBAC → 페이지 라우팅."""
import streamlit as st

st.set_page_config(page_title="Hospital Bid Radar", page_icon="📡", layout="wide")

from hbr.auth.session import require_user  # noqa: E402
from views._common import refresh_button, repo  # noqa: E402

user = require_user(repo())
st.session_state["user"] = user

PAGES = [  # (feature, 파일, 제목, 아이콘)
    ("dashboard", "views/dashboard.py", "Dashboard", "📡"),
    ("bids", "views/bids.py", "입찰공고", "📋"),
    ("awards", "views/awards.py", "낙찰정보", "🏆"),
    ("contracts", "views/contracts.py", "계약정보", "📑"),
    ("hospital", "views/hospital.py", "병원 상세", "🏥"),
    ("competitors", "views/competitors.py", "경쟁사", "🎯"),
    ("copilot", "views/copilot.py", "AI Copilot", "🤖"),
    ("settings", "views/settings.py", "설정", "⚙️"),
]
allowed = [st.Page(f, title=t, icon=i, default=(k == "dashboard")) for k, f, t, i in PAGES
           if k == "settings" or user.can(k)]
pg = st.navigation(allowed)

from hbr.config import get_settings  # noqa: E402

settings = get_settings()
with st.sidebar:
    st.markdown(f"**{user.name}**  \n`{user.role}`")
    if not settings.auth_disabled:
        st.button("로그아웃", on_click=st.logout, width="stretch")
refresh_button()
if not settings.use_supabase:
    st.sidebar.warning("데모 모드: 가상 데이터입니다. Supabase 를 연결하면 실제 데이터가 표시됩니다.")
pg.run()
