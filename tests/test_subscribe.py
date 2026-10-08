import pytest

from hbr import subscribe as sub

S = "test-secret"
T0 = 1_800_000_000.0


def test_code_roundtrip_and_window():
    code = sub.issue_code(S, "a@b.co", "subscribe", T0)
    assert len(code) == 6 and code.isdigit()
    assert sub.verify_code(S, "a@b.co", "subscribe", code, T0 + 60)
    assert sub.verify_code(S, "a@b.co", "subscribe", code, T0 + sub.WINDOW_MIN * 60)      # 다음 시간대도 허용
    assert not sub.verify_code(S, "a@b.co", "subscribe", code, T0 + 3 * sub.WINDOW_MIN * 60)   # 만료


def test_code_bound_to_email_purpose_and_secret():
    code = sub.issue_code(S, "a@b.co", "subscribe", T0)
    assert not sub.verify_code(S, "x@b.co", "subscribe", code, T0)
    assert not sub.verify_code(S, "a@b.co", "unsubscribe", code, T0)
    assert not sub.verify_code("other", "a@b.co", "subscribe", code, T0)
    assert not sub.verify_code(S, "a@b.co", "subscribe", "abc123", T0)
    assert not sub.verify_code("", "a@b.co", "subscribe", code, T0)


def test_issue_without_secret_raises():
    with pytest.raises(sub.SubscribeError):
        sub.issue_code("", "a@b.co", "subscribe")


def test_normalize_email():
    assert sub.normalize_email("  Foo.Bar@Example.COM ") == "foo.bar@example.com"
    for bad in ("", "x", "a@b", "a b@c.com", "a@@c.com", "a" * 250 + "@c.com"):
        with pytest.raises(sub.SubscribeError):
            sub.normalize_email(bad)


def test_domain_restriction(monkeypatch):
    sub.check_domain("anyone@gmail.com")                       # 미설정이면 제한 없음
    monkeypatch.setenv("SUBSCRIBE_ALLOWED_DOMAINS", "sk.com, @skplasma.com")
    sub.check_domain("a@sk.com")
    with pytest.raises(sub.SubscribeError):
        sub.check_domain("a@gmail.com")


def test_subscribe_unsubscribe_lifecycle(repo):
    assert sub.subscribe(repo, "new@x.com") == "created"
    u = repo.get_user("new@x.com")
    assert u["role"] == "viewer" and u["is_active"] and u["report_enabled"]
    assert sub.subscribe(repo, "new@x.com") == "already"
    assert sub.unsubscribe(repo, "new@x.com") is True
    assert repo.get_user("new@x.com")["report_enabled"] is False
    assert sub.unsubscribe(repo, "new@x.com") is False            # 이미 취소
    assert sub.subscribe(repo, "new@x.com") == "enabled"
    assert sub.unsubscribe(repo, "nobody@x.com") is False


def test_subscribe_does_not_reactivate_disabled_or_change_role(repo):
    repo.ensure_user("adm@x.com", "adm", "admin")
    repo.update("users", {"report_enabled": False}, [("email", "eq", "adm@x.com")])
    assert sub.subscribe(repo, "adm@x.com") == "enabled"
    assert repo.get_user("adm@x.com")["role"] == "admin"          # 권한은 그대로
    repo.ensure_user("off@x.com", "off", "viewer")
    repo.update("users", {"is_active": False}, [("email", "eq", "off@x.com")])
    with pytest.raises(sub.SubscribeError):
        sub.subscribe(repo, "off@x.com")


def test_send_code_dry_run_writes_outbox(tmp_path, monkeypatch):
    import hbr.reports.mailer as mailer
    from hbr.config import get_settings

    monkeypatch.setattr(mailer, "OUTBOX", tmp_path)
    monkeypatch.setenv("SUBSCRIBE_SECRET", S)
    assert sub.send_code(get_settings(), "a@b.co", "subscribe") == "dry_run"
    f = next(tmp_path.glob("*.html"))
    assert "인증코드" in f.read_text(encoding="utf-8")
