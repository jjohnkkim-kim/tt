"""Hospital Bid Radar — Streamlit 진입점. 로그인(이메일 가입+관리자 승인 / Entra ID) → RBAC → 페이지 라우팅."""
import sys
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="Hospital Bid Radar", page_icon="📡", layout="wide")


def _deploy_info() -> str:
    """배포 환경 진단 정보 (어떤 커밋/파이썬/파일이 올라와 있는지). 비밀 값은 포함하지 않는다."""
    root = Path(__file__).resolve().parent
    try:
        head = (root / ".git" / "HEAD").read_text().strip()
        ref = head.split(" ", 1)[1] if head.startswith("ref:") else None
        sha = (root / ".git" / ref).read_text().strip() if ref else head
        commit = f"{sha[:7]} ({ref.rsplit('/', 1)[-1] if ref else 'detached'})"
    except Exception:       # noqa: BLE001 — .git 이 없는 배포도 있다
        commit = "알 수 없음"
    files = {f: (root / f).exists() for f in ("hbr/auth/session.py", "hbr/auth/accounts.py", "hbr/auth/passwords.py",
                                              "hbr/config.py", "views/_common.py")}
    return (f"Python {sys.version.split()[0]} / streamlit {st.__version__}\n배포 커밋: {commit}\n앱 경로: {root}\n"
            + "\n".join(f"{'OK     ' if ok else '없음   '}{f}" for f, ok in files.items()))


def _load():
    from hbr.auth.session import logout, require_user
    from views._common import refresh_button, repo
    return logout, require_user, refresh_button, repo


def _purge_stale_modules() -> None:
    """배포 갱신 뒤 서버가 옛 모듈(메모리/바이트코드 캐시)을 들고 있는 경우를 복구한다.
    Streamlit Cloud 는 코드를 갱신해도 프로세스를 재시작하지 않을 수 있어 옛 hbr/views 모듈이 남을 수 있다."""
    import importlib
    import shutil

    for name in [n for n in sys.modules if n == "hbr" or n.startswith("hbr.") or n == "views" or n.startswith("views.")]:
        del sys.modules[name]
    for cache in Path(__file__).resolve().parent.glob("**/__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)
    importlib.invalidate_caches()


def _module_info() -> str:
    mod = sys.modules.get("hbr.auth.session")
    if mod is None:
        return "hbr.auth.session: 불러오지 못함"
    src = Path(getattr(mod, "__file__", "") or "")
    try:
        st_src = f"{src.stat().st_size}B mtime={int(src.stat().st_mtime)}"
    except OSError:
        st_src = "?"
    return (f"hbr.auth.session: logout 정의={'logout' in dir(mod)} / 파일 {st_src}\n"
            f"cached={getattr(mod, '__cached__', None)}")


try:
    logout, require_user, refresh_button, repo = _load()
except ImportError as first_error:
    _purge_stale_modules()                  # 옛 모듈/캐시를 비우고 한 번 더 시도
    try:
        logout, require_user, refresh_button, repo = _load()
    except ImportError as e:
        # Streamlit Cloud 는 일반 예외 메시지를 가려서 원인을 알 수 없다. import 오류는 비밀을 담지 않으므로 화면에 보여 준다.
        st.error("앱 모듈을 불러오지 못했습니다. 아래 내용을 개발자에게 그대로 전달해 주세요.")
        st.code(f"{type(e).__name__}: {e}\n(첫 시도: {first_error})\n\n{_deploy_info()}\n{_module_info()}")
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
