#!/usr/bin/env bash
set -euo pipefail

# Railway provisioning via CLI.
# Requires: RAILWAY_TOKEN (account token) in .deploy.env, and
# .deploy.generated.env with DATABASE_URL + REDIS_URL already populated.

PROJECT_NAME="maya-core"
SERVICE_NAME="maya-core"

# Zscaler (or any corporate MITM) SSL — export root CA so the Railway CLI
# (a Rust binary) trusts the intercepting cert. Auto-generated below if absent.
ZSCALER_CA="$(pwd)/.zscaler-root-ca.pem"
if [[ ! -f "$ZSCALER_CA" ]]; then
  security find-certificate -a -c "Zscaler Root" -p /Library/Keychains/System.keychain \
    > "$ZSCALER_CA" 2>/dev/null || true
fi
if [[ -s "$ZSCALER_CA" ]]; then
  export SSL_CERT_FILE="$ZSCALER_CA"
  export NODE_EXTRA_CA_CERTS="$ZSCALER_CA"
  export REQUESTS_CA_BUNDLE="$ZSCALER_CA"
fi

if ! command -v railway &>/dev/null; then
  echo "  ↪ Installing Railway CLI..."
  npm install -g @railway/cli
fi

# Account tokens authenticate via RAILWAY_API_TOKEN; project tokens use
# RAILWAY_TOKEN. We use an account token, so map it across and drop the other
# so the CLI doesn't pick the wrong one.
export RAILWAY_API_TOKEN="${RAILWAY_TOKEN}"
unset RAILWAY_TOKEN || true

# Create + link project (idempotent: skip if already linked)
if ! railway status &>/dev/null 2>&1; then
  echo "  ↪ Creating Railway project '$PROJECT_NAME'..."
  railway init --name "$PROJECT_NAME" < /dev/null
else
  echo "  ↪ Railway project already linked"
fi

# Link the service; create it first if it doesn't exist yet (idempotent).
if ! railway service "$SERVICE_NAME" < /dev/null 2>/dev/null; then
  echo "  ↪ Creating service '$SERVICE_NAME'..."
  railway add --service "$SERVICE_NAME" < /dev/null
  railway service "$SERVICE_NAME" < /dev/null
fi

# Load connection strings + secrets. (.deploy.env may reset RAILWAY_TOKEN,
# so re-map afterwards.)
set -a
source .deploy.generated.env
source .deploy.env
set +a
export RAILWAY_API_TOKEN="${RAILWAY_TOKEN}"
unset RAILWAY_TOKEN || true

# The app's async SQLAlchemy engine needs the asyncpg URL form, not Neon's raw
# psycopg URL. mem0's pgvector parser handles either, so this is safe for both.
APP_DATABASE_URL="$(uv run python scripts/deploy/asyncpg_url.py)"

echo "  ↪ Setting environment variables..."
# Railway rejects empty values, so only include optional vars when populated.
VAR_ARGS=(
  --set "DATABASE_URL=$APP_DATABASE_URL"
  --set "REDIS_URL=$REDIS_URL"
  --set "XAI_API_KEY=$XAI_API_KEY"
  --set "OPENAI_API_KEY=$OPENAI_API_KEY"
  --set "ENVIRONMENT=production"
  --set "LITELLM_LOG=ERROR"
)
if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
  VAR_ARGS+=(--set "ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY")
fi
# Telegram channel (optional). All three needed for the bot to come online; the
# app registers the webhook at startup when token + base URL are present.
if [[ -n "${TELEGRAM_BOT_TOKEN:-}" ]]; then
  VAR_ARGS+=(--set "TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN")
fi
if [[ -n "${TELEGRAM_WEBHOOK_SECRET:-}" ]]; then
  VAR_ARGS+=(--set "TELEGRAM_WEBHOOK_SECRET=$TELEGRAM_WEBHOOK_SECRET")
fi
if [[ -n "${PUBLIC_BASE_URL:-}" ]]; then
  VAR_ARGS+=(--set "PUBLIC_BASE_URL=$PUBLIC_BASE_URL")
fi
# Google sign-in (optional). Without both, /auth/google/* answers 503 and the
# email+password path still works. The redirect URI defaults to
# {PUBLIC_BASE_URL}/auth/google/callback and must match the Google console.
for var in GOOGLE_CLIENT_ID GOOGLE_CLIENT_SECRET GOOGLE_REDIRECT_URI; do
  if [[ -n "${!var:-}" ]]; then
    VAR_ARGS+=(--set "$var=${!var}")
  fi
done
# Password-reset email (optional). Unset logs the reset link instead of sending
# it — fine for a staging box, not for real users.
for var in RESEND_API_KEY MAIL_FROM PASSWORD_RESET_URL_BASE; do
  if [[ -n "${!var:-}" ]]; then
    VAR_ARGS+=(--set "$var=${!var}")
  fi
done
# Billing (optional). Unset leaves the plans and status readable while checkout
# answers 503. STRIPE_WEBHOOK_SECRET comes from the Stripe dashboard endpoint
# pointing at {PUBLIC_BASE_URL}/billing/webhook.
for var in STRIPE_SECRET_KEY STRIPE_WEBHOOK_SECRET \
           STRIPE_PRICE_PLUS_MONTHLY STRIPE_PRICE_PLUS_YEARLY \
           FREE_DAILY_MESSAGE_LIMIT; do
  if [[ -n "${!var:-}" ]]; then
    VAR_ARGS+=(--set "$var=${!var}")
  fi
done
railway variables --service "$SERVICE_NAME" "${VAR_ARGS[@]}" < /dev/null

# Ensure a public domain exists (idempotent — prints existing if already set).
echo "  ↪ Ensuring public domain..."
railway domain --service "$SERVICE_NAME" < /dev/null 2>&1 | grep -i "url" || true

echo "  ↪ Deploying..."
railway up --service "$SERVICE_NAME" --detach < /dev/null

echo "  ✓ Railway deployment triggered"
