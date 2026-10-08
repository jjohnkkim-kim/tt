#!/usr/bin/env bash
# Azure Container Apps 배포 (az login 후 실행, az CLI 2.60+ 권장).
#
# 필수 환경변수:
#   ACR(전역 고유 이름)  SUPABASE_URL  SUPABASE_SECRET_KEY  SERVICE_KEY
#   ENTRA_TENANT_ID  ENTRA_CLIENT_ID  ENTRA_CLIENT_SECRET  COOKIE_SECRET(예: openssl rand -hex 32)
#   ADMIN_EMAILS  ALLOWED_EMAIL_DOMAINS
# 선택: TEAMS_WEBHOOK_URL SLACK_WEBHOOK_URL SOLAPI_API_KEY SOLAPI_API_SECRET KAKAO_PF_ID KAKAO_SENDER KAKAO_TPL_ALERT KAKAO_TPL_REPORT ANTHROPIC_API_KEY OPENAI_API_KEY SMTP_HOST SMTP_PORT SMTP_USER SMTP_PASSWORD MAIL_FROM
#
# 주의: 정기 실행을 이 스크립트의 Job 으로 하면 GitHub Actions 의 daily-pipeline / daily-report /
#       instant-alerts 스케줄은 꺼야 한다 (둘 다 켜면 수집·알림이 중복 실행됨).
set -euo pipefail

RG=${RG:-rg-bidradar}; LOC=${LOC:-koreacentral}; ENV=${ENV:-cae-bidradar}
ACR=${ACR:?ACR 이름 필요}; APP=${APP:-bidradar-web}
for v in SUPABASE_URL SUPABASE_SECRET_KEY SERVICE_KEY ENTRA_TENANT_ID ENTRA_CLIENT_ID \
         ENTRA_CLIENT_SECRET COOKIE_SECRET ADMIN_EMAILS ALLOWED_EMAIL_DOMAINS; do
  : "${!v:?$v 필요}"
done
IMAGE="$ACR.azurecr.io/bidradar:latest"

az group create -n "$RG" -l "$LOC" -o none
az acr create -n "$ACR" -g "$RG" --sku Basic -o none
az acr build -r "$ACR" -t bidradar:latest .
az containerapp env create -n "$ENV" -g "$RG" -l "$LOC" -o none

# ── 공통 secret / 환경변수 (값은 secret 으로만 저장하고 secretref 로 참조) ──
SECRETS=(supabase-key="$SUPABASE_SECRET_KEY" service-key="$SERVICE_KEY"
         anthropic-key="${ANTHROPIC_API_KEY:-none}" openai-key="${OPENAI_API_KEY:-none}"
         smtp-password="${SMTP_PASSWORD:-none}" teams-webhook="${TEAMS_WEBHOOK_URL:-none}" slack-webhook="${SLACK_WEBHOOK_URL:-none}"
         solapi-key="${SOLAPI_API_KEY:-none}" solapi-secret="${SOLAPI_API_SECRET:-none}")
COMMON_ENV=(SUPABASE_URL="$SUPABASE_URL" SUPABASE_SECRET_KEY=secretref:supabase-key DATA_BACKEND=supabase
            ANTHROPIC_API_KEY=secretref:anthropic-key OPENAI_API_KEY=secretref:openai-key
            SMTP_HOST="${SMTP_HOST:-smtp.office365.com}" SMTP_PORT="${SMTP_PORT:-587}"
            SMTP_USER="${SMTP_USER:-}" SMTP_PASSWORD=secretref:smtp-password
            MAIL_FROM="${MAIL_FROM:-Hospital Bid Radar <bidradar@localhost>}"
            MAIL_DRY_RUN="${MAIL_DRY_RUN:-true}" ADMIN_EMAILS="$ADMIN_EMAILS"
            TEAMS_WEBHOOK_URL=secretref:teams-webhook SLACK_WEBHOOK_URL=secretref:slack-webhook
            SOLAPI_API_KEY=secretref:solapi-key SOLAPI_API_SECRET=secretref:solapi-secret
            KAKAO_PF_ID="${KAKAO_PF_ID:-none}" KAKAO_SENDER="${KAKAO_SENDER:-none}"
            KAKAO_TPL_ALERT="${KAKAO_TPL_ALERT:-none}" KAKAO_TPL_REPORT="${KAKAO_TPL_REPORT:-none}")

# ── 웹앱 (Streamlit). WebSocket 세션 → sticky session. 로그인 설정은 컨테이너 시작 시
#    scripts/write_auth_secrets.py 가 아래 환경변수로 secrets.toml 을 생성한다. ──
az containerapp create -n "$APP" -g "$RG" --environment "$ENV" \
  --image "$IMAGE" --registry-server "$ACR.azurecr.io" --registry-identity system \
  --target-port 8501 --ingress external --min-replicas 1 --max-replicas 2 \
  --secrets "${SECRETS[@]}" entra-secret="$ENTRA_CLIENT_SECRET" cookie-secret="$COOKIE_SECRET" \
  --env-vars "${COMMON_ENV[@]}" AUTH_DISABLED=false ALLOWED_EMAIL_DOMAINS="$ALLOWED_EMAIL_DOMAINS" \
             ENTRA_TENANT_ID="$ENTRA_TENANT_ID" ENTRA_CLIENT_ID="$ENTRA_CLIENT_ID" \
             ENTRA_CLIENT_SECRET=secretref:entra-secret COOKIE_SECRET=secretref:cookie-secret \
             APP_BASE_URL="https://pending.invalid" \
  -o none
az containerapp ingress sticky-sessions set -n "$APP" -g "$RG" --affinity sticky -o none

# FQDN 확정 후 리다이렉트 기준 URL 반영 (새 리비전이 배포되며 secrets.toml 이 다시 생성됨)
FQDN=$(az containerapp show -n "$APP" -g "$RG" --query properties.configuration.ingress.fqdn -o tsv)
az containerapp update -n "$APP" -g "$RG" --set-env-vars APP_BASE_URL="https://$FQDN" -o none

# ── 배치 Job (정시성이 필요하면 GitHub Actions 대신 이쪽 사용). 시각은 UTC cron ──
make_job() {  # name, cron, extra-env..., -- command args...
  local name=$1 cron=$2; shift 2
  az containerapp job create -n "$name" -g "$RG" --environment "$ENV" \
    --trigger-type Schedule --cron-expression "$cron" --replica-timeout 3600 \
    --image "$IMAGE" --registry-server "$ACR.azurecr.io" --registry-identity system \
    --secrets "${SECRETS[@]}" \
    --env-vars "${COMMON_ENV[@]}" SERVICE_KEY=secretref:service-key APP_BASE_URL="https://$FQDN" \
    --command "/bin/sh" --args "-c" "$*" -o none
}
# 06:00 KST — 수집 → 점수 → 알림 생성
make_job bidradar-daily "0 21 * * *" "python scripts/run_pipeline.py --job all"
# 07:40 KST 기동, 08:00 KST 까지 대기 후 Daily Report 발송 (재실행해도 중복 발송 없음)
make_job bidradar-report "40 22 * * *" "python scripts/send_daily_report.py --wait-until 08:00"
# 평일 09~20시 30분마다 — 신규 입찰 수집 → 즉시 알림 발송
make_job bidradar-alerts "*/30 0-10 * * 1-5" \
  "python scripts/run_pipeline.py --job bids --days 1 && python scripts/run_pipeline.py --job alerts && python scripts/dispatch_alerts.py"

cat <<MSG

배포 완료: https://$FQDN
다음을 직접 해주세요:
 1) Entra 앱 등록 > Authentication 의 Redirect URI 를  https://$FQDN/oauth2callback  으로 설정
 2) 메일을 실제로 보내려면 SMTP_* 를 넣고 MAIL_DRY_RUN=false 로 재배포
 3) GitHub Actions 의 daily-pipeline / daily-report / instant-alerts 스케줄 비활성화 (중복 방지)
MSG
