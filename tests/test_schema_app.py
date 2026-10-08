"""SQL 스키마와 코드가 쓰는 컬럼의 일치 + Streamlit 화면 스모크 테스트."""
from pathlib import Path

import pytest

from hbr.analytics.alerts import generate_alerts
from hbr.analytics.scoring import ensure_scores
from hbr.auth.rbac import User
from tests.conftest import TODAY

ROOT = Path(__file__).resolve().parents[1]


def sql_columns() -> dict[str, set[str]]:
    pglast = pytest.importorskip("pglast")
    out = {}
    for stmt in pglast.parse_sql((ROOT / "sql/schema.sql").read_text(encoding="utf-8")):
        node = stmt.stmt
        if type(node).__name__ == "CreateStmt":
            out[node.relation.relname] = {e.colname for e in node.tableElts if type(e).__name__ == "ColumnDef"}
    return out


def test_sql_parses_and_has_required_tables():
    cols = sql_columns()
    for t in ["hospitals", "bids", "awards", "contracts", "competitors", "opportunity_scores", "alerts",
              "subscriptions", "users", "email_reports"]:
        assert t in cols


def test_rows_written_by_code_fit_schema(demo_repo):
    from hbr.reports.mailer import send_daily_reports
    from hbr.config import get_settings

    demo_repo.ensure_user("s@x.com", "영업", "sales")
    ensure_scores(demo_repo, TODAY)
    generate_alerts(demo_repo, TODAY)
    send_daily_reports(demo_repo, get_settings(), TODAY, briefing=False)
    demo_repo.log_run("bids", "success", __import__("datetime").datetime.now(), __import__("datetime").datetime.now())
    cols = sql_columns()
    for table, allowed in cols.items():
        for row in demo_repo.b.select(table):
            extra = set(row) - allowed
            assert not extra, f"{table}: 스키마에 없는 컬럼 {extra}"


def test_sql_upsert_keys_are_unique_in_schema():
    from hbr.store.backends import UNIQUE_KEYS

    sql = (ROOT / "sql/schema.sql").read_text(encoding="utf-8")
    for table, keys in UNIQUE_KEYS.items():
        if len(keys) == 1:
            assert f"{keys[0]}" in sql
    assert "unique (hospital_id, score_date)" in sql and "unique (report_date, recipient)" in sql


PAGES = ["dashboard", "bids", "awards", "contracts", "hospital", "competitors", "copilot", "settings"]


@pytest.mark.parametrize("page", PAGES)
def test_page_renders(page):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(ROOT / f"views/{page}.py"), default_timeout=90)
    at.session_state["user"] = User(1, "dev@local", "dev", "admin")
    at.run()
    assert not at.exception, [e.value for e in at.exception]


def test_main_app_runs_in_dev_mode():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90).run()
    assert not at.exception and len(at.metric) >= 6


def test_copilot_page_answers_question():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(ROOT / "views/copilot.py"), default_timeout=90)
    at.session_state["user"] = User(1, "dev@local", "dev", "admin")
    at.run()
    at.chat_input[0].set_value("방문 우선순위를 추천해줘").run()
    assert not at.exception and len(at.chat_message) == 2


def test_write_auth_secrets(tmp_path):
    import tomllib

    from scripts.write_auth_secrets import main, render

    env = {"AUTH_MODE": "entra", "ENTRA_TENANT_ID": "tid", "ENTRA_CLIENT_ID": "cid", "ENTRA_CLIENT_SECRET": 'se"cr\\et',
           "COOKIE_SECRET": "ck", "APP_BASE_URL": "https://app.example.com/"}
    cfg = tomllib.loads(render(env))                      # 특수문자 포함 값도 유효한 TOML
    assert cfg["auth"]["redirect_uri"] == "https://app.example.com/oauth2callback"
    assert cfg["auth"]["microsoft"]["client_secret"] == 'se"cr\\et'
    assert cfg["auth"]["microsoft"]["server_metadata_url"].startswith("https://login.microsoftonline.com/tid/v2.0")
    out = tmp_path / ".streamlit" / "secrets.toml"
    assert main(env, out) == 0 and out.exists() and oct(out.stat().st_mode)[-3:] == "600"
    assert main({k: v for k, v in env.items() if k != "COOKIE_SECRET"}, tmp_path / "x.toml") == 1   # 누락 시 시작 거부
    assert main({"AUTH_MODE": "entra", "AUTH_DISABLED": "true"}, tmp_path / "y.toml") == 0 and not (tmp_path / "y.toml").exists()
    assert main({}, tmp_path / "z.toml") == 0 and not (tmp_path / "z.toml").exists()     # 기본(이메일 가입) 모드는 Entra 설정 불필요


def test_env_example_runs_in_demo_mode(monkeypatch):
    """README 대로 .env.example 을 그대로 복사해도 Supabase 로 착각하지 않고 데모로 실행돼야 한다."""
    from dotenv import dotenv_values

    from hbr.config import get_settings

    for k, v in dotenv_values(ROOT / ".env.example").items():
        monkeypatch.setenv(k, v or "")
    monkeypatch.setenv("DATA_BACKEND", "auto")
    s = get_settings()
    assert s.use_supabase is False and s.service_key == ""


@pytest.mark.parametrize("url,key,expected", [
    ("https://YOUR_PROJECT.supabase.co", "YOUR_SUPABASE_SECRET_KEY", False),      # 예전 .env.example 값
    ("", "", False), ("https://abcdefgh.supabase.co", "", False), ("", "sb_secret_abc", False),
    ("https://abcdefgh.supabase.co", "sb_secret_abc", True)])
def test_supabase_placeholder_detection(monkeypatch, url, key, expected):
    from hbr.config import get_settings

    monkeypatch.setenv("DATA_BACKEND", "auto")
    monkeypatch.setenv("SUPABASE_URL", url)
    monkeypatch.setenv("SUPABASE_SECRET_KEY", key)
    assert get_settings().use_supabase is expected


def test_app_shows_friendly_error_when_supabase_unreachable(monkeypatch):
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    import views._common as common

    def boom(*a, **k):
        raise ConnectionError("getaddrinfo failed")
    monkeypatch.setattr(common, "get_repo", boom)
    st.cache_resource.clear()
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90).run()
    st.cache_resource.clear()
    assert not at.exception                                        # 트레이스백 대신 안내 문구
    assert any("연결하지 못했습니다" in e.value for e in at.error)
    assert any("ConnectionError" in c.value for c in at.caption)


@pytest.fixture
def restore_modules():
    """복구 경로는 hbr/views 모듈을 모두 비우고 다시 불러오므로, 다른 테스트(예: 예외 클래스 동일성)에 영향이 없게 원복한다."""
    import sys

    def mine(k):
        return k == "hbr" or k.startswith("hbr.") or k == "views" or k.startswith("views.")
    saved = {k: v for k, v in sys.modules.items() if mine(k)}
    yield
    for k in [k for k in sys.modules if mine(k)]:
        del sys.modules[k]
    sys.modules.update(saved)


def test_app_recovers_from_stale_modules_left_in_memory(monkeypatch, restore_modules):
    """배포 갱신 뒤 서버 메모리에 '옛 버전' 모듈이 남아 있어도(logout 없음) 자동으로 비우고 다시 불러와 정상 기동한다."""
    import sys
    import types

    from streamlit.testing.v1 import AppTest

    stale = types.ModuleType("hbr.auth.session")          # logout 이 없는 '옛 버전' 모듈
    stale.require_user = lambda repo: None
    monkeypatch.setitem(sys.modules, "hbr.auth.session", stale)
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90).run()
    assert not at.exception and not at.error
    assert len(at.metric) >= 6                              # 정상 화면(Dashboard)까지 도달
    assert hasattr(sys.modules["hbr.auth.session"], "logout")        # 실제 모듈로 교체됨


def test_app_removes_stale_bytecode_cache_on_retry(monkeypatch, restore_modules):
    import sys
    import types

    from streamlit.testing.v1 import AppTest

    cache = ROOT / "hbr" / "__pycache__"
    cache.mkdir(exist_ok=True)
    marker = cache / "stale_marker.txt"
    marker.write_text("x")
    stale = types.ModuleType("hbr.auth.session")
    stale.require_user = lambda repo: None
    monkeypatch.setitem(sys.modules, "hbr.auth.session", stale)
    AppTest.from_file(str(ROOT / "app.py"), default_timeout=90).run()
    assert not marker.exists()                              # 복구 경로에서 __pycache__ 를 비움


def test_app_shows_import_error_details_when_recovery_fails(monkeypatch, restore_modules):
    """다시 시도해도 실패하면 가려진 트레이스백 대신 원인과 배포 정보를 화면에 보여 준다."""
    import importlib.abc
    import sys

    from streamlit.testing.v1 import AppTest

    class Boom(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path=None, target=None):
            if name == "hbr.auth.session":
                raise ImportError("cannot import name 'logout' from 'hbr.auth.session' (simulated)")
            return None

    import startup_check

    calls = []
    monkeypatch.setattr(startup_check, "repair_worktree", lambda root, enabled: calls.append(enabled) or "stub")
    monkeypatch.setattr(sys, "meta_path", [Boom(), *sys.meta_path])
    monkeypatch.delitem(sys.modules, "hbr.auth.session", raising=False)
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90).run()
    assert not at.exception
    assert any("불러오지 못했습니다" in e.value for e in at.error)
    shown = "\n".join(c.value for c in at.code)
    assert "ImportError" in shown and "cannot import name 'logout'" in shown and "첫 시도" in shown
    assert "Python 3." in shown and "hbr/auth/accounts.py" in shown and "배포 커밋" in shown
    assert "작업 트리: stub" in shown and "hbr/auth/session.py: " in shown and "'def logout' 포함=True" in shown
    assert calls == [False]                     # 로컬(/mount/src 아님)에서는 자동 복원 꺼짐 → 개발 중 수정 보호


def test_streamlit_secrets_take_precedence_over_env(monkeypatch):
    """Cloud 에서 Secrets 를 고치면 환경변수에는 옛 값이 남을 수 있어, 앱에서는 Secrets 를 먼저 읽는다."""
    import streamlit as st

    from hbr.config import _get

    monkeypatch.setenv("ADMIN_SETUP_CODE", "from-env")
    monkeypatch.setattr(st, "secrets", {"ADMIN_SETUP_CODE": "from-secrets", "EMPTY_ONE": ""})
    assert _get("ADMIN_SETUP_CODE") == "from-secrets"
    monkeypatch.setenv("EMPTY_ONE", "env-fallback")
    assert _get("EMPTY_ONE") == "env-fallback"                     # 빈 Secrets 값은 무시
    assert _get("NOT_ANYWHERE_XYZ", "dflt") == "dflt"


def test_storage_label_and_key_hide_secret():
    from hbr.config import get_settings

    s = get_settings()
    s2 = s.__class__(**{**s.__dict__, "data_backend": "supabase", "supabase_url": "https://abcd.supabase.co",
                        "supabase_key": "sb_secret_TOPSECRET"})
    assert s2.storage_label == "abcd.supabase.co" and "TOPSECRET" not in str(s2.storage_key())
    assert s.__class__(**{**s.__dict__, "data_backend": "memory"}).storage_label == "demo"
