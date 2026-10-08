#!/usr/bin/env bash
# Azure Container Apps 배포 예시 (az login 후 실행). 비밀값은 Key Vault/Container Apps secret 으로 주입.
set -euo pipefail
RG=${RG:-rg-bidradar}; LOC=${LOC:-koreacentral}; ENV=${ENV:-cae-bidradar}
ACR=${ACR:?ACR 이름 필요}; APP=${APP:-bidradar-web}

az group create -n "$RG" -l "$LOC"
az acr create -n "$ACR" -g "$RG" --sku Basic
az acr build -r "$ACR" -t bidradar:latest .
az containerapp env create -n "$ENV" -g "$RG" -l "$LOC"

# 웹앱 (Streamlit) — 세션 고정 필요(WebSocket): replica 1~2, sticky sessions
az containerapp create -n "$APP" -g "$RG" --environment "$ENV" \
  --image "$ACR.azurecr.io/bidradar:latest" --registry-server "$ACR.azurecr.io" \
  --target-port 8501 --ingress external --min-replicas 1 --max-replicas 2 \
  --secrets supabase-key="$SUPABASE_SECRET_KEY" anthropic-key="${ANTHROPIC_API_KEY:-}" \
            cookie-secret="$COOKIE_SECRET" entra-secret="$ENTRA_CLIENT_SECRET" \
  --env-vars SUPABASE_URL="$SUPABASE_URL" SUPABASE_SECRET_KEY=secretref:supabase-key \
             ANTHROPIC_API_KEY=secretref:anthropic-key DATA_BACKEND=supabase AUTH_DISABLED=false \
             ADMIN_EMAILS="$ADMIN_EMAILS" ALLOWED_EMAIL_DOMAINS="$ALLOWED_EMAIL_DOMAINS"
az containerapp ingress sticky-sessions set -n "$APP" -g "$RG" --affinity sticky

# 배치 Job (정시 실행이 필요하면 GitHub Actions 대신 Container Apps Job 의 cron 사용)
az containerapp job create -n bidradar-daily -g "$RG" --environment "$ENV" \
  --trigger-type Schedule --cron-expression "0 21 * * *" \
  --image "$ACR.azurecr.io/bidradar:latest" --registry-server "$ACR.azurecr.io" \
  --secrets supabase-key="$SUPABASE_SECRET_KEY" service-key="$SERVICE_KEY" \
  --replica-timeout 3600 --command "python" --args "scripts/run_pipeline.py" "--job" "all" \
  --env-vars SUPABASE_URL="$SUPABASE_URL" SUPABASE_SECRET_KEY=secretref:supabase-key SERVICE_KEY=secretref:service-key DATA_BACKEND=supabase
echo "Entra 앱 등록의 Redirect URI 를 https://<FQDN>/oauth2callback 으로 설정하세요."
