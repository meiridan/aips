#!/usr/bin/env bash
# Stop: verify before claiming done.
#
#   1. Uncommitted Python under maya/ or tests/ -> run the unit suite (~8s, 379
#      tests, no Postgres needed) and mypy over maya/. Both are green as of the
#      commit that added this hook, so any failure here is something you just
#      introduced. Turns "should be fine" into evidence.
#   2. Uncommitted frontend/ changes with no matching maya/static/ change -> the
#      committed bundle is stale and production would keep serving the old SPA.
#
# Exit 2 blocks the stop once and feeds stderr back to Claude; stop_hook_active
# lets the second stop through, so this nags exactly once.
set -uo pipefail

payload=$(cat)
[ "$(printf '%s' "$payload" | jq -r '.stop_hook_active // false')" = "true" ] && exit 0

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}" || exit 0
git rev-parse --git-dir >/dev/null 2>&1 || exit 0

changed=$(git status --porcelain -- maya tests frontend 2>/dev/null)
[ -n "$changed" ] || exit 0

problems=""

if printf '%s' "$changed" | grep -Eq '\.py$'; then
  if ! out=$(uv run pytest tests/unit -q --tb=short -p no:warnings 2>&1); then
    problems+="Unit tests FAIL. Fix them before reporting this done:

$(printf '%s' "$out" | tail -30)

"
  fi
  if ! out=$(uv run mypy maya 2>&1); then
    problems+="mypy FAILS on maya/. It was clean before this change:

$(printf '%s' "$out" | grep -v '^mypy.ini:' | tail -25)

"
  fi
fi

if printf '%s' "$changed" | grep -q '^.. *frontend/' \
   && ! printf '%s' "$changed" | grep -q 'maya/static/'; then
  problems+="frontend/ has uncommitted changes but maya/static/ does not.

maya/static/ is the committed build output — Railway's railpack build runs no
Node step, so production serves whatever is committed there. Run 'make ui' and
include maya/static/ in the change, or say explicitly why the rebuild is not
needed yet.
"
fi

[ -z "$problems" ] && exit 0
printf '%s' "$problems" >&2
exit 2
