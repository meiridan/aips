#!/usr/bin/env bash
set -euo pipefail

# Maya Core — full provisioning
# Usage: ./scripts/deploy/provision.sh
# Requires: .deploy.env with all tokens

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT_DIR"

# TLS trust. On a machine behind Zscaler (or any corporate MITM proxy), HTTPS is
# re-signed with a private root CA that isn't in certifi. Export that root so all
# tools (Python, asyncpg, the Railway CLI) trust it. Falls back to certifi when
# no such proxy is present.
ZSCALER_CA="$(pwd)/.zscaler-root-ca.pem"
if [[ ! -f "$ZSCALER_CA" ]]; then
  security find-certificate -a -c "Zscaler Root" -p /Library/Keychains/System.keychain \
    > "$ZSCALER_CA" 2>/dev/null || true
fi
if [[ -s "$ZSCALER_CA" ]]; then
  export SSL_CERT_FILE="$ZSCALER_CA"
else
  rm -f "$ZSCALER_CA"
  export SSL_CERT_FILE="$(uv run python -m certifi)"
fi
export REQUESTS_CA_BUNDLE="$SSL_CERT_FILE"
export NODE_EXTRA_CA_CERTS="$SSL_CERT_FILE"

if [[ ! -f .deploy.env ]]; then
  echo "❌ .deploy.env not found. See deployment doc §1."
  exit 1
fi
set -a; source .deploy.env; set +a

if ! command -v npm &>/dev/null; then
  echo "❌ npm required for Railway CLI. Install Node.js first."
  exit 1
fi

# Clear generated env from any previous run
rm -f .deploy.generated.env

echo "════════════════════════════════════════"
echo "   Maya Core — Provisioning"
echo "════════════════════════════════════════"

echo ""
echo "▶ [1/6] Provisioning Neon database..."
uv run python scripts/deploy/provision_neon.py

echo ""
echo "▶ [2/6] Provisioning Upstash Redis..."
uv run python scripts/deploy/provision_upstash.py

set -a; source .deploy.generated.env; set +a

echo ""
echo "▶ [3/6] Enabling pgvector extension..."
uv run python scripts/deploy/enable_pgvector.py

echo ""
echo "▶ [4/6] Running database migrations..."
# Railway's builder (railpack) deploys via the Procfile and does not run a build
# hook, so migrations are applied here against Neon directly.
DATABASE_URL="$(uv run python scripts/deploy/asyncpg_url.py)" uv run alembic upgrade head

echo ""
echo "▶ [5/6] Provisioning Railway services..."
bash scripts/deploy/provision_railway.sh

echo ""
echo "▶ [6/6] Running smoke test..."
# Point the app config at the asyncpg URL (same form the deployed service uses).
export DATABASE_URL="$(uv run python scripts/deploy/asyncpg_url.py)"
uv run python scripts/smoke_test.py

echo ""
echo "════════════════════════════════════════"
echo "   ✅ Provisioning complete"
echo "════════════════════════════════════════"
echo ""
echo "Generated connection strings are in .deploy.generated.env"
