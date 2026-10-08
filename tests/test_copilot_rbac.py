import json
from types import SimpleNamespace as NS

import pytest

from hbr.ai.copilot import Copilot
from hbr.ai.tools import TOOL_SPECS
from hbr.auth.rbac import User, domain_allowed, role_for_new_user
from hbr.config import get_settings
from tests.conftest import TODAY


@pytest.fixture
def copilot(demo_repo):
    return Copilot(demo_repo, get_settings(), TODAY)


@pytest.mark.parametrize("q,tool", [
    ("최근 90일 이내 계약종료 예정 병원은?", "list_expiring_contracts"),
    ("이번 달 가장 중요한 입찰은?", "important_bids"),
    ("GC가 가장 많이 수주한 병원은?", "competitor_top_hospitals"),
    ("이번 주 새로 발생한 대학병원 입찰은?", "recent_bids"),
    ("방문 우선순위를 추천해줘", "visit_priorities"),
    ("Opportunity Score 상위 병원을 보여줘", "top_opportunities"),
    ("서울대학교병원 알려줘", "hospital_summary"),
])
def test_rule_router(copilot, q, tool):
    ans = copilot.ask(q)
    assert ans.mode == "rules" and ans.tools_used == [tool] and ans.text


def test_rule_router_university_bids_not_empty(copilot):
    assert "해당하는 입찰이 없습니다" not in copilot.ask("이번 주 새로 발생한 대학병원 입찰은?").text


def test_unknown_question_and_tool(copilot):
    assert copilot.ask("안녕").tools_used == []
    assert "error" in copilot.runner.run("drop_database", {})
    assert "error" in copilot.runner.run("top_opportunities", {"bogus": 1})
    assert "error" in copilot.runner.run("hospital_summary", {"hospital": "없는병원"})


def test_tool_specs_are_valid():
    names = [t["name"] for t in TOOL_SPECS]
    assert len(names) == len(set(names))
    assert all(t["input_schema"]["type"] == "object" and t["description"] for t in TOOL_SPECS)


class FakeAnthropic:
    """1차: tool_use 요청 → 2차: 최종 텍스트."""
    def __init__(self):
        self.calls = []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        if len(self.calls) == 1:
            return NS(stop_reason="tool_use", content=[NS(type="tool_use", id="t1", name="top_opportunities", input={"limit": 2})])
        return NS(stop_reason="end_turn", content=[NS(type="text", text="1위는 ...")])


def test_anthropic_tool_loop(copilot):
    fake = FakeAnthropic()
    ans = copilot._ask_anthropic("상위 병원?", [], client=fake)
    assert ans.text == "1위는 ..." and ans.tools_used == ["top_opportunities"] and ans.mode == "anthropic"
    result_msg = fake.calls[1]["messages"][-1]["content"][0]
    assert result_msg["type"] == "tool_result" and len(json.loads(result_msg["content"])["opportunities"]) == 2
    assert fake.calls[0]["tools"] == TOOL_SPECS and "지시문이 아닙니다" in fake.calls[0]["system"]


def test_anthropic_runaway_tool_loop_is_bounded(copilot):
    class Forever(FakeAnthropic):
        def create(self, **kw):
            self.calls.append(kw)
            return NS(stop_reason="tool_use", content=[NS(type="tool_use", id="t", name="top_opportunities", input={})])
    fake = Forever()
    ans = copilot._ask_anthropic("x", [], client=fake)
    assert len(fake.calls) == 6 and "완성하지 못했습니다" in ans.text


def test_openai_tool_loop(copilot):
    calls = []

    class FakeOpenAI:
        def __init__(self):
            self.chat = NS(completions=self)

        def create(self, **kw):
            calls.append(kw)
            if len(calls) == 1:
                tc = NS(id="c1", function=NS(name="visit_priorities", arguments='{"limit": 1}'))
                return NS(choices=[NS(message=NS(content=None, tool_calls=[tc]))])
            return NS(choices=[NS(message=NS(content="방문 1순위", tool_calls=None))])
    ans = copilot._ask_openai("방문?", [], client=FakeOpenAI())
    assert ans.text == "방문 1순위" and ans.tools_used == ["visit_priorities"]


def test_llm_failure_degrades_to_rules(demo_repo, monkeypatch):
    s = get_settings().__class__(**{**get_settings().__dict__, "llm_provider": "anthropic", "anthropic_api_key": "k"})
    c = Copilot(demo_repo, s, TODAY)
    monkeypatch.setattr(c, "_ask_anthropic", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("503")))
    ans = c.ask("방문 우선순위를 추천해줘")
    assert ans.mode == "rules" and "기본 분석 모드" in ans.text


def test_rbac():
    viewer, sales, mgr, admin = (User(i, f"{r}@x.com", r, r) for i, r in enumerate(["viewer", "sales", "manager", "admin"]))
    assert viewer.can("dashboard") and not viewer.can("copilot") and not viewer.can("download")
    assert sales.can("copilot") and sales.can("download") and not sales.can("admin")
    assert mgr.can("team") and not mgr.can("admin") and admin.can("admin")
    assert admin.can("undefined-feature")                   # 미정의 기능은 admin 만 (deny by default)
    assert not mgr.can("undefined-feature")
    assert not User(1, "a", "a", "hacker").can("dashboard")


def test_auth_helpers():
    assert domain_allowed("a@corp.com", ["corp.com"]) and not domain_allowed("a@evil.com", ["corp.com"])
    assert domain_allowed("a@any.com", [])
    assert role_for_new_user("Boss@corp.com", ["boss@corp.com"]) == "admin"
    assert role_for_new_user("x@corp.com", ["boss@corp.com"]) == "viewer"
