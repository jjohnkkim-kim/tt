from datetime import date

import pytest

from hbr import plans
from hbr.admin_stats import overview
from hbr.auth.rbac import User
from hbr.store.repo import Repo
from hbr.store.backends import MemoryBackend
from hbr.team import TeamError, set_member


def mk():
    return Repo(MemoryBackend())


def user(r, email, role, cid, **kw):
    u = r.ensure_user(email, email.split("@")[0], role)
    r.update("users", {"company_id": cid, "status": "approved", "is_active": True, **kw}, [("id", "eq", u["id"])])
    return r.get_user(email)


def test_plan_expiry_and_defaults():
    assert plans.plan_of(None) == "free" and plans.plan_of({"plan": "pro"}) == "pro"
    assert plans.plan_of({"plan": "pro", "plan_until": "2026-01-01"}, date(2026, 10, 8)) == "free"
    assert plans.plan_of({"plan": "pro", "plan_until": "2026-12-31"}, date(2026, 10, 8)) == "pro"
    assert plans.plan_of({"plan": "weird"}) == "free"


def test_product_limit_blocks_new_but_not_updates():
    r = mk()
    c = r.create_company("가나제약")
    for n in ("a", "b", "c"):
        r.save_product(c["id"], n)
    with pytest.raises(plans.PlanLimitError, match="3"):
        r.save_product(c["id"], "d")
    r.save_product(c["id"], "a", ingredient="x")                       # 기존 제품 수정은 통과
    r.set_plan(c["id"], "pro")
    r.save_product(c["id"], "d")
    assert len(r.list_products(c["id"])) == 4


def test_seat_limit_on_assign():
    r = mk()
    c = r.create_company("가나제약")
    us = [user(r, f"u{i}@x.com", "viewer", None) for i in range(3)]
    r.assign_company(us[0]["id"], c["id"]); r.assign_company(us[1]["id"], c["id"])
    with pytest.raises(plans.PlanLimitError):
        r.assign_company(us[2]["id"], c["id"])
    r.assign_company(us[0]["id"], c["id"])                              # 이미 소속이면 통과
    r.set_plan(c["id"], "pro"); r.assign_company(us[2]["id"], c["id"])
    assert r.seats_used(c["id"]) == 3


def test_set_plan_rejects_unknown():
    r = mk(); c = r.create_company("가나제약")
    with pytest.raises(ValueError):
        r.set_plan(c["id"], "gold")


def test_team_manager_rules():
    r = mk()
    a, b = r.create_company("A사"), r.create_company("B사")
    r.set_plan(a["id"], "team"); r.set_plan(b["id"], "team")
    mgr = user(r, "m@a.com", "manager", a["id"]); mem = user(r, "v@a.com", "viewer", a["id"])
    adm = user(r, "adm@a.com", "admin", a["id"]); other = user(r, "o@b.com", "viewer", b["id"])
    actor = User(mgr["id"], mgr["email"], "m", "manager", a["id"])
    set_member(r, actor, mem["id"], role="sales")
    assert r.get_user("v@a.com")["role"] == "sales"
    set_member(r, actor, mem["id"], is_active=False)
    assert r.get_user("v@a.com")["is_active"] is False
    for tid, kw in ((other["id"], {"role": "sales"}), (adm["id"], {"role": "viewer"}), (mgr["id"], {"role": "viewer"}), (mem["id"], {"role": "admin"})):
        with pytest.raises(TeamError):
            set_member(r, actor, tid, **kw)
    with pytest.raises(TeamError):
        set_member(r, User(mem["id"], "v@a.com", "v", "sales", a["id"]), mem["id"], role="viewer")        # 매니저 미만은 불가


def test_admin_overview_counts():
    r = mk()
    c = r.create_company("가나제약"); r.save_product(c["id"], "알부민")
    user(r, "a@x.com", "admin", c["id"]); user(r, "p@x.com", "viewer", None, status="pending")
    o = overview(r, date(2026, 10, 8))
    assert o["companies"] == 1 and o["users"] == 2 and o["pending"] == 1 and o["no_company_users"] == 1
    row = o["table"].iloc[0]
    assert row["플랜"] == "Free" and row["사용자"] == 1 and row["제품"] == 1
