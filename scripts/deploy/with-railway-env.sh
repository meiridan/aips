#!/usr/bin/env bash
set -euo pipefail

# Run a railway CLI command with the environment it needs on this machine:
# corporate-proxy CA trust + account-token auth + project/service link.
# Usage: bash scripts/deploy/with-railway-env.sh railway logs

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT_DIR"

ZSCALER_CA="$ROOT_DIR/.zscaler-root-ca.pem"
if [[ ! -f "$ZSCALER_CA" ]]; then
  security find-certificate -a -c "Zscaler Root" -p /Library/Keychains/System.keychain \
    > "$ZSCALER_CA" 2>/dev/null || true
fi
if [[ -s "$ZSCALER_CA" ]]; then
  export SSL_CERT_FILE="$ZSCALER_CA"
  export NODE_EXTRA_CA_CERTS="$ZSCALER_CA"
  export REQUESTS_CA_BUNDLE="$ZSCALER_CA"
else
  rm -f "$ZSCALER_CA"
fi

if [[ -f .deploy.env ]]; then
  set -a; source .deploy.env; set +a
fi

# Account token → RAILWAY_API_TOKEN (project tokens use RAILWAY_TOKEN).
if [[ -n "${RAILWAY_TOKEN:-}" ]]; then
  export RAILWAY_API_TOKEN="$RAILWAY_TOKEN"
  unset RAILWAY_TOKEN
fi

exec "$@"
