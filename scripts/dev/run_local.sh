#!/usr/bin/env bash
set -euo pipefail

# Maya Core — run the whole app locally, nothing in the cloud.
#
# Brings up Postgres+pgvector, applies migrations, builds the Hebrew SPA, and
# serves both channels from one uvicorn process (maya.web:app) — the same shape
# as production, on your machine.
#
#   bash scripts/dev/run_local.sh [options]
#
#   --check         boot, smoke-test every endpoint, shut down, report. No server left running.
#   --port N        listen on N (default 8000)
#   --host H        bind address (default 127.0.0.1; use 0.0.0.0 to reach it from your phone)
#   --skip-ui       don't rebuild the SPA (use the bundle already in maya/static/)
#   --no-reload     don't auto-restart the server when Python files change
#   --reset-onboarding  send the app back to the creation wizard (keeps your data)
#   --reset-db      DESTRUCTIVE: drop every table and re-migrate (keeps the container)
#   --fresh         DESTRUCTIVE: also delete the Postgres volume — all data, permanently
#   --yes           skip the confirmation prompt for the destructive flags
#
# Postgres is only managed when DATABASE_URL points at localhost. Point it
# somewhere else (Neon, a shared box) and the container step is skipped.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT_DIR"

PORT=8000
HOST=127.0.0.1
CHECK=0
SKIP_UI=0
NO_RELOAD=0
RESET_DB=0
RESET_ONBOARDING=0
FRESH=0
ASSUME_YES=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check)      CHECK=1 ;;
    --port)       PORT="${2:?--port needs a value}"; shift ;;
    --host)       HOST="${2:?--host needs a value}"; shift ;;
    --skip-ui)    SKIP_UI=1 ;;
    --no-reload)  NO_RELOAD=1 ;;
    --reset-onboarding) RESET_ONBOARDING=1 ;;
    --reset-db)   RESET_DB=1 ;;
    --fresh)      FRESH=1; RESET_DB=1 ;;
    --yes|-y)     ASSUME_YES=1 ;;
    -h|--help)    sed -n '3,23p' "$0"; exit 0 ;;
    *) echo "❌ Unknown option: $1 (try --help)"; exit 2 ;;
  esac
  shift
done

step() { echo ""; echo "▶ $*"; }
warn() { echo "  ⚠ $*"; }
die()  { echo "❌ $*"; exit 1; }

# ── preflight ────────────────────────────────────────────────────────────────
step "[1/5] Preflight"

command -v uv >/dev/null || die "uv not found. Install it: https://docs.astral.sh/uv/"

if [[ ! -f .env ]]; then
  [[ -f .env.example ]] || die ".env and .env.example are both missing."
  cp .env.example .env
  warn "created .env from .env.example — fill in OPENAI_API_KEY (and XAI_API_KEY) or"
  warn "  the UI will load but Maya cannot reply."
fi

# Read DATABASE_URL the way the app does, so we manage the right database.
DB_URL="$(uv run python -c 'from maya.config import get_settings; print(get_settings().database_url)')"
case "$DB_URL" in
  *@localhost:*|*@127.0.0.1:*) LOCAL_DB=1 ;;
  *) LOCAL_DB=0 ;;
esac

if [[ $LOCAL_DB -eq 1 ]]; then
  command -v docker >/dev/null || die "docker not found, and DATABASE_URL points at localhost."
  if ! docker info >/dev/null 2>&1; then
    echo "❌ The Docker daemon is not running."
    echo "   Start Docker Desktop and approve its privileged-access prompt, then rerun."
    echo "   (Docker asks for your admin password on first start — this script cannot answer it.)"
    echo "   Already have Postgres elsewhere? Point DATABASE_URL at it in .env to skip Docker."
    exit 1
  fi
  echo "  ✓ docker running · local Postgres will be managed by this script"
else
  echo "  ✓ DATABASE_URL is remote — skipping the Postgres container"
fi

if [[ $SKIP_UI -eq 0 ]]; then
  command -v npm >/dev/null || die "npm not found (needed to build the SPA). Use --skip-ui to skip."
fi

# Confirm before destroying anything.
if [[ $RESET_DB -eq 1 && $ASSUME_YES -eq 0 ]]; then
  echo ""
  if [[ $FRESH -eq 1 ]]; then
    echo "  --fresh DELETES the Postgres volume: every message, memory, and companion,"
    echo "  permanently, with no backup."
  else
    echo "  --reset-db DROPS every table and re-migrates. All local data is lost."
  fi
  read -r -p "  Continue? [y/N] " reply
  [[ "$reply" =~ ^[Yy]$ ]] || { echo "  Aborted."; exit 1; }
fi

# ── dependencies ─────────────────────────────────────────────────────────────
step "[2/5] Python dependencies"
uv sync --quiet
echo "  ✓ uv sync"

# ── database ─────────────────────────────────────────────────────────────────
step "[3/5] Database"
if [[ $LOCAL_DB -eq 1 ]]; then
  if [[ $FRESH -eq 1 ]]; then
    echo "  ↪ removing container + volume..."
    docker compose down -v >/dev/null 2>&1 || true
  fi
  docker compose up -d >/dev/null
  echo -n "  ↪ waiting for Postgres"
  for _ in $(seq 1 40); do
    if docker compose exec -T db pg_isready -U postgres -d maya >/dev/null 2>&1; then
      echo " ✓"; break
    fi
    printf '.'; sleep 1
  done
  docker compose exec -T db pg_isready -U postgres -d maya >/dev/null 2>&1 \
    || die "Postgres did not become ready. Check: docker compose logs db"
fi

if [[ $RESET_DB -eq 1 && $FRESH -eq 0 ]]; then
  echo "  ↪ dropping all tables..."
  uv run alembic downgrade base >/dev/null
fi
uv run alembic upgrade head >/dev/null
echo "  ✓ migrations at head ($(uv run alembic current 2>/dev/null | tail -1))"

if [[ $RESET_ONBOARDING -eq 1 ]]; then
  echo "  ↪ clearing onboarded_at so the app opens on the creation wizard..."
  uv run python scripts/dev/reset_onboarding.py | sed 's/^/  /'
fi

# ── frontend ─────────────────────────────────────────────────────────────────
step "[4/5] Frontend"
if [[ $SKIP_UI -eq 1 ]]; then
  [[ -f maya/static/index.html ]] \
    || die "--skip-ui was passed but maya/static/index.html does not exist. Run without it once."
  echo "  ↪ skipped (--skip-ui), serving the existing bundle"
else
  if [[ -f frontend/package-lock.json ]]; then
    (cd frontend && npm ci --silent)
  else
    (cd frontend && npm install --silent)
  fi
  (cd frontend && npm run --silent build)
  echo "  ✓ SPA built into maya/static/"
fi

BASE="http://${HOST/0.0.0.0/127.0.0.1}:$PORT"

# ── serve ────────────────────────────────────────────────────────────────────
if [[ $CHECK -eq 0 ]]; then
  step "[5/5] Serving"
  # The living prompt log: every prompt actually sent, plus the reply it drew.
  # Local-only by default — nothing sets this in production.
  export MAYA_PROMPT_LOG="${MAYA_PROMPT_LOG:-logs/prompts.log}"
  echo "  Web UI     $BASE"
  echo "  Debug view $BASE/?debug=1"
  echo "  API docs   $BASE/docs"
  echo "  Prompt log $MAYA_PROMPT_LOG  (uv run maya prompt-log -f)"
  echo ""
  echo "  Ctrl-C to stop."
  RELOAD_ARGS=(--reload --reload-dir maya)
  [[ $NO_RELOAD -eq 1 ]] && RELOAD_ARGS=()
  # macOS ships bash 3.2, where an empty array counts as unset under `set -u`,
  # so --no-reload would abort here. The `[@]+` guard expands to nothing instead.
  exec uv run uvicorn maya.web:app --host "$HOST" --port "$PORT" \
    ${RELOAD_ARGS[@]+"${RELOAD_ARGS[@]}"}
fi

# ── --check: boot, probe, tear down ──────────────────────────────────────────
step "[5/5] Smoke test"
LOG="$(mktemp -t maya-local-check)"
uv run uvicorn maya.web:app --host 127.0.0.1 --port "$PORT" > "$LOG" 2>&1 &
SERVER_PID=$!
cleanup() { kill "$SERVER_PID" 2>/dev/null || true; wait "$SERVER_PID" 2>/dev/null || true; }
trap cleanup EXIT

echo -n "  ↪ waiting for the server"
for _ in $(seq 1 60); do
  curl -fsS -o /dev/null --max-time 3 "$BASE/api/catalog" 2>/dev/null && { echo " ✓"; break; }
  kill -0 "$SERVER_PID" 2>/dev/null || { echo ""; echo "--- server output ---"; cat "$LOG"; die "server exited during startup"; }
  printf '.'; sleep 1
done

FAILED=0
probe() { # name url jq-ish-grep
  local name="$1" url="$2" needle="${3:-}"
  local body code
  body="$(curl -fsS --max-time 20 "$url" 2>/dev/null || true)"
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$url" || echo 000)"
  if [[ "$code" != "200" ]]; then
    echo "  ✗ $name → HTTP $code"; FAILED=1; return
  fi
  if [[ -n "$needle" && "$body" != *"$needle"* ]]; then
    echo "  ✗ $name → 200 but missing expected content: $needle"; FAILED=1; return
  fi
  echo "  ✓ $name"
}

probe "GET /                     (SPA shell, RTL)" "$BASE/" 'dir="rtl"'
probe "GET /api/catalog          (wizard options)" "$BASE/api/catalog" '"hair_color"'
probe "GET /api/companion        (DB reachable)"   "$BASE/api/companion" '"onboarded"'
probe "GET /companion/response_length"             "$BASE/companion/response_length" '"level"'

BUNDLE="$(curl -fsS --max-time 10 "$BASE/" 2>/dev/null | grep -o '/assets/[A-Za-z0-9._-]*\.js' | head -1 || true)"
if [[ -n "$BUNDLE" ]]; then
  probe "GET $BUNDLE" "$BASE$BUNDLE"
else
  echo "  ✗ index.html references no JS bundle"; FAILED=1
fi

echo ""
if [[ $FAILED -eq 0 ]]; then
  echo "════════════════════════════════════════"
  echo "   ✅ Local stack healthy — $BASE"
  echo "════════════════════════════════════════"
else
  echo "════════════════════════════════════════"
  echo "   ❌ Smoke test failed"
  echo "════════════════════════════════════════"
  echo "--- server output ---"
  tail -30 "$LOG"
fi
exit $FAILED
