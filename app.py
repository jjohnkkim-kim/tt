"""Hospital Bid Radar — Streamlit 진입점. 로그인(이메일 가입+관리자 승인 / Entra ID) → RBAC → 페이지 라우팅."""
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="Hospital Bid Radar", page_icon="📡", layout="wide")

ROOT = Path(__file__).resolve().parent


def _load():
    from hbr.auth.session import logout, require_user
    from views._common import refresh_button, repo
    return logout, require_user, refresh_button, repo


# 배포 갱신이 일부만 반영되면(메모리/캐시의 옛 모듈, 또는 디스크의 옛 .py) import 가 실패한다.
# 단계적으로 복구를 시도하고, 그래도 안 되면 가려진 트레이스백 대신 원인을 화면에 보여 준다(비밀 값 없음).
try:
    logout, require_user, refresh_button, repo = _load()
except ImportError as first_error:
    import startup_check as sc

    sc.purge_modules(ROOT)                                  # ① 메모리/바이트코드 캐시 정리
    try:
        logout, require_user, refresh_button, repo = _load()
    except ImportError:
        repair = sc.repair_worktree(ROOT, sc.auto_repair_enabled(ROOT))   # ② (배포 서버만) 커밋과 다른 .py 를 HEAD 로 복원
        sc.purge_modules(ROOT)
        try:
            logout, require_user, refresh_button, repo = _load()
        except ImportError as e:
            st.error("앱 모듈을 불러오지 못했습니다. 아래 내용을 개발자에게 그대로 전달해 주세요.")
            st.code(f"{type(e).__name__}: {e}\n(첫 시도: {first_error})\n작업 트리: {repair}\n\n"
                    f"{sc.deploy_info(ROOT, st.__version__)}\n"
                    f"{sc.file_report(ROOT, 'hbr/auth/session.py', 'def logout')}")
            st.stop()

try:
    user = require_user(repo())
except Exception as e:      # noqa: BLE001 — st.stop() 등 스트림릿 제어 예외는 BaseException 이라 잡히지 않는다
    st.error("데이터 저장소(Supabase)에 연결하지 못했습니다.")
    st.markdown("- 데모로 보려면 `.env` 의 `SUPABASE_URL`, `SUPABASE_SECRET_KEY` 를 **비워** 두세요.\n"
                "- 실데이터를 쓰려면 두 값이 정확한지(Project URL, Secret key) 확인하세요.")
    st.caption(f"{type(e).__name__}: {str(e)[:200]}")
    st.stop()
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
        st.button("로그아웃", on_click=logout, width="stretch")
refresh_button()
if not settings.use_supabase:
    st.sidebar.warning("데모 모드: 가상 데이터입니다. Supabase 를 연결하면 실제 데이터가 표시됩니다.")
pg.run()
