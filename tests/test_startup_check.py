"""startup_check: 배포 서버의 '옛 파일/옛 모듈' 복구와 진단. 실제 저장소 대신 임시 git 저장소로 검증한다."""
import subprocess
import sys
from pathlib import Path

import pytest

import startup_check as sc

NEW = "def require_user():\n    pass\n\n\ndef logout():\n    pass\n"
OLD = "def require_user():\n    pass\n"            # logout 이 없는 '옛 파일'


@pytest.fixture
def repo(tmp_path) -> Path:
    def run(*a):
        subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True)
    run("init", "-q")
    run("config", "user.email", "t@t")
    run("config", "user.name", "t")
    (tmp_path / "hbr" / "auth").mkdir(parents=True)
    (tmp_path / "hbr" / "auth" / "session.py").write_text(NEW)
    (tmp_path / "README.md").write_text("doc")
    run("add", "-A")
    run("commit", "-qm", "init")
    return tmp_path


def test_clean_worktree(repo):
    assert sc.changed_tracked_files(repo) == []
    assert sc.repair_worktree(repo, enabled=True) == "작업 트리 = 커밋 (차이 없음)"


def test_stale_file_restored_when_enabled(repo):
    f = repo / "hbr" / "auth" / "session.py"
    f.write_text(OLD)                                   # 배포 동기화 실패로 디스크에 옛 내용이 남은 상황
    assert "'def logout' 포함=False" in sc.file_report(repo, "hbr/auth/session.py", "def logout")
    assert "커밋과 다름" in sc.file_report(repo, "hbr/auth/session.py", "def logout")
    msg = sc.repair_worktree(repo, enabled=True)
    assert "복원" in msg and "hbr/auth/session.py" in msg
    assert f.read_text() == NEW
    rep = sc.file_report(repo, "hbr/auth/session.py", "def logout")
    assert "'def logout' 포함=True" in rep and "커밋과 같음" in rep


def test_disabled_never_touches_files(repo):
    f = repo / "hbr" / "auth" / "session.py"
    f.write_text(OLD)                                   # 로컬 개발 중 저장 안 한 수정
    msg = sc.repair_worktree(repo, enabled=False)
    assert "자동 복원 꺼짐" in msg and f.read_text() == OLD


def test_untracked_and_non_code_files_untouched(repo):
    (repo / ".streamlit").mkdir()
    secret = repo / ".streamlit" / "secrets.toml"
    secret.write_text("KEY='x'")                        # 추적되지 않는 비밀 파일
    (repo / "README.md").write_text("edited")           # 코드 아닌 변경
    msg = sc.repair_worktree(repo, enabled=True)
    assert msg.startswith("코드 외 변경만") and secret.read_text() == "KEY='x'"
    assert (repo / "README.md").read_text() == "edited"


def test_no_git_repository(tmp_path):
    assert sc.changed_tracked_files(tmp_path) is None
    assert "git 사용 불가" in sc.repair_worktree(tmp_path, enabled=True)
    (tmp_path / "x.py").write_text("a")
    assert "커밋과 알 수 없음" in sc.file_report(tmp_path, "x.py", "a")
    assert "읽기 실패" in sc.file_report(tmp_path, "nope.py", "a")


@pytest.mark.parametrize("flag,path,expected", [
    ("", "/mount/src/tt", True), ("", "/home/user/tt", False),
    ("1", "/home/user/tt", True), ("0", "/mount/src/tt", False), ("off", "/mount/src/tt", False)])
def test_auto_repair_enabled(monkeypatch, flag, path, expected):
    monkeypatch.setenv("HBR_AUTO_REPAIR", flag)
    monkeypatch.setattr(Path, "resolve", lambda self: self)
    assert sc.auto_repair_enabled(Path(path)) is expected


def test_purge_modules_clears_memory_and_bytecode(tmp_path, monkeypatch):
    import types
    (tmp_path / "hbr" / "__pycache__").mkdir(parents=True)
    (tmp_path / "hbr" / "__pycache__" / "x.pyc").write_bytes(b"0")
    (tmp_path / "other" / "__pycache__").mkdir(parents=True)          # 다른 패키지 캐시는 그대로
    for name in ("hbr.fake_zz", "views.fake_zz", "hbrx_fake_zz"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    saved = {k: v for k, v in sys.modules.items() if k.split(".")[0] in sc.PACKAGES}
    try:
        sc.purge_modules(tmp_path)
        assert "hbr.fake_zz" not in sys.modules and "views.fake_zz" not in sys.modules
        assert "hbrx_fake_zz" in sys.modules                           # 이름만 비슷한 모듈은 유지
        assert not (tmp_path / "hbr" / "__pycache__").exists() and (tmp_path / "other" / "__pycache__").exists()
    finally:
        sys.modules.update(saved)


def test_deploy_info_reads_commit(repo):
    info = sc.deploy_info(repo, "1.0")
    head = subprocess.run(["git", "rev-parse", "--short=7", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
    assert f"배포 커밋: {head}" in info and "streamlit 1.0" in info and "OK     hbr/auth/session.py" in info


def test_first_changed_path_not_truncated(repo):
    """회귀: git 출력 앞 공백을 잘라 첫 경로의 첫 글자가 사라지던 버그 (' M hbr/...' → 'br/...')."""
    (repo / "hbr" / "auth" / "session.py").write_text(OLD)
    (repo / "README.md").write_text("x")
    assert sorted(sc.changed_tracked_files(repo)) == ["README.md", "hbr/auth/session.py"]
