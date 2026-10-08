"""앱 시작 점검/복구 (표준 라이브러리만 사용 — hbr 패키지가 깨져 있어도 동작해야 한다).

배포 환경(Streamlit Cloud 등)에서 코드 갱신이 일부만 반영되면 '파일은 최신 커밋인데 일부 .py 가 옛 내용'
이거나 '메모리/바이트코드 캐시에 옛 모듈'이 남을 수 있다. app.py 는 import 실패 시 여기 함수로
① 모듈·캐시 정리 ② 작업 트리를 커밋(HEAD) 상태로 복원 ③ 원인 진단을 수행한다.
"""
from __future__ import annotations

import hashlib
import importlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

PACKAGES = ("hbr", "views")


def git(root: Path, *args: str, raw: bool = False) -> str | None:
    """git 명령 실행 결과(stdout). git 이 없거나 실패하면 None.
    raw=True 는 앞 공백을 보존한다(--porcelain 의 ' M path' 처럼 상태 칸이 공백일 수 있음)."""
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return r.stdout.rstrip("\n") if raw else r.stdout.strip()


def purge_modules(root: Path) -> None:
    """메모리의 hbr/views 모듈과 __pycache__ 를 비워 다음 import 가 디스크의 최신 파일을 읽게 한다."""
    for name in [n for n in sys.modules if n.split(".")[0] in PACKAGES]:
        del sys.modules[name]
    for pkg in PACKAGES:
        for cache in (root / pkg).glob("**/__pycache__"):
            shutil.rmtree(cache, ignore_errors=True)
    importlib.invalidate_caches()


def changed_tracked_files(root: Path) -> list[str] | None:
    """커밋(HEAD)과 내용이 다른 추적 파일 목록. git 사용 불가면 None."""
    out = git(root, "status", "--porcelain", "--untracked-files=no", raw=True)
    if out is None:
        return None
    # 형식: 'XY path' (상태 2칸 + 공백). 이름 변경은 'R  old -> new'
    return [line[3:].split(" -> ")[-1] for line in out.splitlines() if len(line) > 3]


def auto_repair_enabled(root: Path) -> bool:
    """자동 복원은 배포 서버에서만. 로컬 개발 중의 '저장 안 한 수정'을 되돌리면 안 되기 때문이다.
    HBR_AUTO_REPAIR=1/0 으로 강제할 수 있고, 미설정이면 Streamlit Community Cloud 경로(/mount/src/)에서만 켠다."""
    flag = os.getenv("HBR_AUTO_REPAIR", "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        return True
    if flag in {"0", "false", "no", "off"}:
        return False
    return str(root.resolve()).startswith("/mount/src/")


def repair_worktree(root: Path, enabled: bool) -> str:
    """커밋과 다른 .py 파일을 HEAD 내용으로 되돌린다. 추적되지 않는 파일(secrets 등)은 건드리지 않는다."""
    changed = changed_tracked_files(root)
    if changed is None:
        return "git 사용 불가 — 작업 트리 확인 못 함"
    if not changed:
        return "작업 트리 = 커밋 (차이 없음)"
    code = [f for f in changed if f.endswith(".py")]
    if not code:
        return "코드 외 변경만 있음: " + ", ".join(changed[:10])
    if not enabled:
        return "커밋과 다른 파일(자동 복원 꺼짐 — 로컬 개발 환경): " + ", ".join(code[:10])
    if git(root, "checkout", "HEAD", "--", *code) is None:
        return "복원 실패: " + ", ".join(code[:10])
    return "커밋 내용으로 복원: " + ", ".join(code[:10])


def _blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def file_report(root: Path, rel: str, needle: str) -> str:
    """디스크 파일이 커밋과 같은지(크기·git blob 해시·특정 문자열 포함 여부)."""
    path = root / rel
    try:
        data = path.read_bytes()
    except OSError as e:
        return f"{rel}: 읽기 실패 ({type(e).__name__})"
    head = git(root, "rev-parse", f"HEAD:{rel}")
    same = "알 수 없음" if head is None else ("같음" if head == _blob_sha(data) else "다름(옛 파일?)")
    return f"{rel}: {len(data)}B, '{needle}' 포함={needle.encode() in data}, 커밋과 {same}"


def deploy_info(root: Path, streamlit_version: str) -> str:
    try:
        head = (root / ".git" / "HEAD").read_text().strip()
        ref = head.split(" ", 1)[1] if head.startswith("ref:") else None
        sha = (root / ".git" / ref).read_text().strip() if ref else head
        commit = f"{sha[:7]} ({ref.rsplit('/', 1)[-1] if ref else 'detached'})"
    except OSError:
        commit = (git(root, "rev-parse", "--short", "HEAD") or "알 수 없음")
    files = ("hbr/auth/session.py", "hbr/auth/accounts.py", "hbr/auth/passwords.py", "hbr/config.py", "views/_common.py")
    return (f"Python {sys.version.split()[0]} / streamlit {streamlit_version}\n배포 커밋: {commit}\n앱 경로: {root}\n"
            + "\n".join(f"{'OK     ' if (root / f).exists() else '없음   '}{f}" for f in files))
