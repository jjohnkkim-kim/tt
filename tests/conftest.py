import os
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.update(DATA_BACKEND="memory", AUTH_DISABLED="true", MAIL_DRY_RUN="true",
                  LLM_PROVIDER="none", SERVICE_KEY="", SUPABASE_URL="", SUPABASE_SECRET_KEY="")

from hbr.store.backends import MemoryBackend   # noqa: E402
from hbr.store.repo import Repo                # noqa: E402

TODAY = date(2026, 10, 8)


@pytest.fixture
def repo():
    r = Repo(MemoryBackend())
    r.seed_competitors()
    return r


@pytest.fixture
def demo_repo():
    from hbr.store.demo_data import load_demo

    r = Repo(MemoryBackend())
    r.seed_competitors()
    load_demo(r, today=TODAY)
    return r


@pytest.fixture(autouse=True)
def _outbox(tmp_path, monkeypatch):
    import hbr.reports.mailer as m

    monkeypatch.setattr(m, "OUTBOX", tmp_path / "outbox")
