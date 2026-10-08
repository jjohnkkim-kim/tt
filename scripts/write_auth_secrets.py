"""컨테이너 시작 시 환경변수로 Streamlit OIDC 설정(~/.streamlit/secrets.toml)을 생성한다.

Streamlit 의 st.login() 은 환경변수가 아니라 secrets.toml 의 [auth] 를 읽는다.
Container Apps secret(환경변수)로 주입한 값을 여기서 파일로 만든다.
필요한 환경변수: ENTRA_TENANT_ID, ENTRA_CLIENT_ID, ENTRA_CLIENT_SECRET, COOKIE_SECRET, APP_BASE_URL
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REQUIRED = ["ENTRA_TENANT_ID", "ENTRA_CLIENT_ID", "ENTRA_CLIENT_SECRET", "COOKIE_SECRET", "APP_BASE_URL"]


def render(env) -> str:
    q = json.dumps     # JSON 문자열은 TOML basic string 과 호환 (따옴표/역슬래시 안전 처리)
    tenant = env["ENTRA_TENANT_ID"]
    return "\n".join([
        "[auth]",
        f"redirect_uri = {q(env['APP_BASE_URL'].rstrip('/') + '/oauth2callback')}",
        f"cookie_secret = {q(env['COOKIE_SECRET'])}",
        "",
        "[auth.microsoft]",
        f"client_id = {q(env['ENTRA_CLIENT_ID'])}",
        f"client_secret = {q(env['ENTRA_CLIENT_SECRET'])}",
        f"server_metadata_url = {q(f'https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration')}",
        'client_kwargs = { prompt = "select_account" }',
        "",
    ])


def main(env=os.environ, path: Path | None = None) -> int:
    if env.get("AUTH_MODE", "password").strip().lower() != "entra":
        print("AUTH_MODE=password — Microsoft 로그인 설정이 필요 없습니다")
        return 0
    if env.get("AUTH_DISABLED", "").strip().lower() in {"1", "true", "yes", "on"}:
        print("AUTH_DISABLED=true — 로그인 설정을 만들지 않습니다 (운영에서는 사용 금지)")
        return 0
    missing = [k for k in REQUIRED if not env.get(k)]
    if missing:
        print(f"로그인 설정 환경변수 누락: {', '.join(missing)} "
              "(로컬 테스트라면 AUTH_DISABLED=true 로 실행)", file=sys.stderr)
        return 1
    path = path or Path.home() / ".streamlit" / "secrets.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(env), encoding="utf-8")
    path.chmod(0o600)
    print(f"Streamlit 인증 설정 생성: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
