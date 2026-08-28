#!/usr/bin/env bash
set -euo pipefail

# Maya Core — frontend-only deploy.
#
# Builds the SPA (frontend/ -> maya/static/) and ships it to the running Railway
# service. Skips everything provision.sh does for the backend: no Neon/Upstash
# provisioning, no migrations, no environment-variable writes.
#
#   bash scripts/deploy/deploy_frontend.sh [options]
#
#   --build-only   build + verify the bundle, don't deploy
#   --skip-tests   don't run the frontend unit tests before building
#   --no-verify    don't poll the live URL for the new bundle after deploying
#   --yes          don't ask for confirmation before deploying
#
# Caveat worth knowing: Railway's `railway up` uploads the whole working tree
# (minus .railwayignore), so a deploy carries whatever backend code is on disk
# too. This script only guarantees it changes nothing *else* deliberately — it
# warns below if your backend files are dirty.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT_DIR"

SERVICE_NAME="maya-core"
STATIC_DIR="maya/static"
BUILD_ONLY=0
SKIP_TESTS=0
NO_VERIFY=0
ASSUME_YES=0

for arg in "$@"; do
  case "$arg" in
    --build-only) BUILD_ONLY=1 ;;
    --skip-tests) SKIP_TESTS=1 ;;
    --no-verify)  NO_VERIFY=1 ;;
    --yes|-y)     ASSUME_YES=1 ;;
    -h|--help)    sed -n '3,20p' "$0"; exit 0 ;;
    *) echo "❌ Unknown option: $arg (try --help)"; exit 2 ;;
  esac
done

step() { echo ""; echo "▶ $*"; }
warn() { echo "  ⚠ $*"; }

# ── TLS trust ────────────────────────────────────────────────────────────────
# Behind a corporate MITM proxy (Zscaler here) npm's HTTPS is re-signed with a
# private root CA that Node doesn't ship. Export it so `npm ci` can reach the
# registry. The Railway CLI gets the same treatment inside with-railway-env.sh.
ZSCALER_CA="$ROOT_DIR/.zscaler-root-ca.pem"
if [[ ! -f "$ZSCALER_CA" ]]; then
  security find-certificate -a -c "Zscaler Root" -p /Library/Keychains/System.keychain \
    > "$ZSCALER_CA" 2>/dev/null || true
fi
if [[ -s "$ZSCALER_CA" ]]; then
  export NODE_EXTRA_CA_CERTS="$ZSCALER_CA"
  export SSL_CERT_FILE="$ZSCALER_CA"
else
  rm -f "$ZSCALER_CA"
fi

# ── preflight ────────────────────────────────────────────────────────────────
step "[1/5] Preflight"

command -v npm >/dev/null || { echo "❌ npm not found. Install Node.js first."; exit 1; }
[[ -d frontend ]] || { echo "❌ frontend/ not found."; exit 1; }
echo "  ✓ node $(node -v), npm $(npm -v)"

if [[ $BUILD_ONLY -eq 0 ]]; then
  [[ -f .deploy.env ]] || { echo "❌ .deploy.env not found. See MAYA_DEPLOYMENT_SCRIPTABLE.md §1."; exit 1; }
  # Only read PUBLIC_BASE_URL here; with-railway-env.sh owns the auth wiring.
  PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-$(grep -E '^PUBLIC_BASE_URL=' .deploy.env | cut -d= -f2- || true)}"
  if ! command -v railway >/dev/null; then
    echo "  ↪ Installing Railway CLI..."
    npm install -g @railway/cli
  fi
fi

# The built bundle is committed (railpack runs no build hook), so a deploy from a
# dirty tree can ship something that is not in git. Warn, don't block.
if git rev-parse --git-dir >/dev/null 2>&1; then
  if [[ -n "$(git status --porcelain -- 'maya/*.py' 'maya/**/*.py' 2>/dev/null)" ]]; then
    warn "backend .py files are modified — 'railway up' uploads the working tree,"
    warn "  so this deploy will carry those changes too. Ctrl-C if that's not intended."
  fi
fi

# ── test ─────────────────────────────────────────────────────────────────────
step "[2/5] Frontend tests"
if [[ $SKIP_TESTS -eq 1 ]]; then
  echo "  ↪ skipped (--skip-tests)"
else
  (cd frontend && npm run --silent test)
  echo "  ✓ tests passed"
fi

# ── build ────────────────────────────────────────────────────────────────────
step "[3/5] Building SPA -> $STATIC_DIR"
if [[ -f frontend/package-lock.json ]]; then
  (cd frontend && npm ci --silent)
else
  warn "no package-lock.json — falling back to 'npm install' (build is not reproducible)"
  (cd frontend && npm install --silent)
fi
(cd frontend && npm run --silent build)

# ── verify the bundle ────────────────────────────────────────────────────────
step "[4/5] Verifying build output"
INDEX="$STATIC_DIR/index.html"
[[ -f "$INDEX" ]] || { echo "❌ $INDEX missing — the Vite build did not produce a bundle."; exit 1; }

BUNDLE_JS="$(grep -o '/assets/[A-Za-z0-9._-]*\.js' "$INDEX" | head -1 || true)"
BUNDLE_CSS="$(grep -o '/assets/[A-Za-z0-9._-]*\.css' "$INDEX" | head -1 || true)"
[[ -n "$BUNDLE_JS" ]] || { echo "❌ $INDEX references no JS bundle."; exit 1; }
for asset in "$BUNDLE_JS" "$BUNDLE_CSS"; do
  [[ -z "$asset" ]] && continue
  [[ -f "$STATIC_DIR$asset" ]] || { echo "❌ $INDEX references $asset but the file is missing."; exit 1; }
done
grep -q 'dir="rtl"' "$INDEX" || warn "index.html is missing dir=\"rtl\" — the Hebrew layout will render LTR."

echo "  ✓ js  $BUNDLE_JS  ($(du -h "$STATIC_DIR$BUNDLE_JS" | cut -f1))"
[[ -n "$BUNDLE_CSS" ]] && echo "  ✓ css $BUNDLE_CSS ($(du -h "$STATIC_DIR$BUNDLE_CSS" | cut -f1))"

if [[ $BUILD_ONLY -eq 1 ]]; then
  echo ""
  echo "✅ Build only — nothing deployed. Commit $STATIC_DIR, then rerun without --build-only."
  exit 0
fi

# ── deploy ───────────────────────────────────────────────────────────────────
step "[5/5] Deploying to Railway service '$SERVICE_NAME'"
if [[ $ASSUME_YES -eq 0 ]]; then
  echo "  This publishes the new UI to ${PUBLIC_BASE_URL:-the live service}."
  read -r -p "  Deploy now? [y/N] " reply
  [[ "$reply" =~ ^[Yy]$ ]] || { echo "  Aborted."; exit 1; }
fi

bash scripts/deploy/with-railway-env.sh \
  railway up --service "$SERVICE_NAME" --detach < /dev/null

# ── confirm the live site actually serves the new bundle ─────────────────────
if [[ $NO_VERIFY -eq 1 || -z "${PUBLIC_BASE_URL:-}" ]]; then
  echo ""
  echo "✅ Deploy triggered. Verify manually: ${PUBLIC_BASE_URL:-<PUBLIC_BASE_URL unset>}"
  exit 0
fi

step "Waiting for $PUBLIC_BASE_URL to serve $BUNDLE_JS"
BASE="${PUBLIC_BASE_URL%/}"
for attempt in $(seq 1 60); do
  live="$(curl -fsS --max-time 10 "$BASE/" 2>/dev/null || true)"
  if [[ "$live" == *"$BUNDLE_JS"* ]]; then
    code="$(curl -fsS -o /dev/null -w '%{http_code}' --max-time 10 "$BASE$BUNDLE_JS" || echo 000)"
    if [[ "$code" == "200" ]]; then
      echo ""
      echo "════════════════════════════════════════"
      echo "   ✅ Frontend live at $BASE"
      echo "════════════════════════════════════════"
      exit 0
    fi
  fi
  printf '.'
  sleep 5
done

echo ""
warn "Timed out after 5 min waiting for the new bundle."
warn "The build may still be running — check: make deploy.logs"
exit 1
