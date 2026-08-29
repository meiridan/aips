#!/usr/bin/env bash
# PostToolUse (Write|Edit|MultiEdit): format Python, then surface the cross-file
# rituals this repo has that no single file records.
#
# Reminders are informational (additionalContext), never blocking — they fire
# exactly when the relevant file is touched, which is cheaper and more reliable
# than carrying the same rules in CLAUDE.md on every turn.
set -uo pipefail

payload=$(cat)
file=$(printf '%s' "$payload" | jq -r '.tool_input.file_path // empty')
[ -n "$file" ] || exit 0

root="${CLAUDE_PROJECT_DIR:-$(pwd)}"
rel="${file#"$root"/}"

case "$rel" in
  *.py)
    uv run ruff format "$file" >/dev/null 2>&1
    uv run ruff check --fix "$file" >/dev/null 2>&1
    ;;
esac

notes=()

case "$rel" in
  maya/web.py)
    notes+=("Reply-flow parity: maya/web.py and maya/telegram/service.py share the orchestrator's critical path but are separate entry points. If this change touched the reply flow, make the matching change in maya/telegram/service.py and update tests/unit/test_telegram.py + tests/unit/test_web_*.py.")
    ;;
  maya/telegram/service.py)
    notes+=("Reply-flow parity: maya/telegram/service.py and maya/web.py share the orchestrator's critical path but are separate entry points. If this change touched the reply flow, make the matching change in maya/web.py and update tests/unit/test_web_*.py + tests/unit/test_telegram.py.")
    ;;
  maya/companions/catalog.py)
    notes+=("Wizard-option fan-out: every option in catalog.py must also be accepted by maya/companions/persona_spec.py and covered in tests/unit/test_persona_catalog.py. The frontend reads the catalog from the API — never hardcode an option there.")
    ;;
  frontend/*)
    notes+=("Frontend build output is COMMITTED: Railway's railpack build runs no Node step, so maya/static/ is the deployed bundle. Run 'make ui' and commit maya/static/ before this ships, or production keeps serving the old SPA.")
    ;;
  maya/conversation/prompt_builder.py)
    notes+=("PHASE3_SYSTEM_TEMPLATE feeds 'maya show-prompt' — if you added a {placeholder}, add its origin to maya/conversation/prompt_debug.py::_sources (tests/unit/test_prompt_debug.py enforces this). Directives here compose with the moment's own guidance; dump the assembled prompt before assuming a behaviour bug.")
    ;;
  maya/db/models.py)
    notes+=("Schema change: add an Alembic revision in maya/db/migrations/versions/. Railway has no build-time hook — migrations are applied locally against Neon, so an unmigrated model change fails in production, not here.")
    ;;
esac

[ ${#notes[@]} -eq 0 ] && exit 0

printf '%s' "${notes[*]}" | jq -Rs \
  '{hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: .}}'
exit 0
