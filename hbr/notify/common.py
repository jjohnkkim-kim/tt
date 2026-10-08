"""웹훅 채널(Teams/Slack) 공통: 재시도 정책, 외부 텍스트 정리."""
from __future__ import annotations

import re
import time
from urllib.parse import urlparse

import requests

_BRACKETS = re.compile(r"[\[\]]")


def host_ok(url: str, exact: tuple[str, ...] = (), suffixes: tuple[str, ...] = ()) -> bool:
    """https 이고 허용된 호스트(정확히 일치 또는 서브도메인 접미사)인지. 임의 URL 로 데이터가 나가는 것을 막는다."""
    u = urlparse(url or "")
    host = (u.hostname or "").lower()
    return u.scheme == "https" and (host in exact or any(host.endswith(s) for s in suffixes))


def clean_text(text, limit: int = 300) -> str:
    """외부(공고명 등) 텍스트 정리: 대괄호(Markdown 링크 문법) 제거 + 개행 제거 + 길이 제한."""
    s = _BRACKETS.sub("", str(text or "")).replace("\r", " ").replace("\n", " ").strip()
    return s if len(s) <= limit else s[: limit - 1] + "…"


def post_with_retry(url: str, payload: dict, error_cls: type[Exception], label: str,
                    ok_codes: tuple[int, ...] = (200, 202), retries: int = 3, session=None) -> None:
    """5xx/429/네트워크 오류만 지수 백오프로 재시도, 4xx 는 즉시 실패. 오류 메시지에 URL(비밀)을 넣지 않는다."""
    http = session or requests
    last = None
    for attempt in range(retries):
        try:
            r = http.post(url, json=payload, timeout=15)
            if r.status_code in ok_codes:
                return
            last = f"HTTP {r.status_code}"
            if r.status_code < 500 and r.status_code != 429:
                break
        except requests.RequestException as e:
            last = type(e).__name__
        time.sleep(2 ** attempt)
    raise error_cls(f"{label} 전송 실패: {last}")
