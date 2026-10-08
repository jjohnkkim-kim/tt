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

    env = {"ENTRA_TENANT_ID": "tid", "ENTRA_CLIENT_ID": "cid", "ENTRA_CLIENT_SECRET": 'se"cr\\et',
           "COOKIE_SECRET": "ck", "APP_BASE_URL": "https://app.example.com/"}
    cfg = tomllib.loads(render(env))                      # 특수문자 포함 값도 유효한 TOML
    assert cfg["auth"]["redirect_uri"] == "https://app.example.com/oauth2callback"
    assert cfg["auth"]["microsoft"]["client_secret"] == 'se"cr\\et'
    assert cfg["auth"]["microsoft"]["server_metadata_url"].startswith("https://login.microsoftonline.com/tid/v2.0")
    out = tmp_path / ".streamlit" / "secrets.toml"
    assert main(env, out) == 0 and out.exists() and oct(out.stat().st_mode)[-3:] == "600"
    assert main({k: v for k, v in env.items() if k != "COOKIE_SECRET"}, tmp_path / "x.toml") == 1   # 누락 시 시작 거부
    assert main({"AUTH_DISABLED": "true"}, tmp_path / "y.toml") == 0 and not (tmp_path / "y.toml").exists()


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
