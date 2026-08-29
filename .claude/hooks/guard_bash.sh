#!/usr/bin/env bash
# PreToolUse (Bash): block the two commands in this repo that cost real money or
# destroy production. Exit 2 blocks the call and shows stderr to Claude.
set -uo pipefail

cmd=$(cat | jq -r '.tool_input.command // empty')
[ -n "$cmd" ] || exit 0

# Strip the cheap opt-in target so `make eval.behaviors` is never mistaken for
# the full suite.
probe=${cmd//eval.behaviors/}

if printf '%s' "$probe" | grep -Eq '(^|[^.[:alnum:]])make[[:space:]]+eval([^.[:alnum:]]|$)|evaluate-suite'; then
  cat >&2 <<'MSG'
BLOCKED: the full eval suite costs ~$50 in real LLM calls and runs 30-day sims.

Per the Makefile it is meant for `eval-required` PRs or a weekly cron, not an
ad-hoc run. Use `make eval.behaviors` (targeted assertions, far cheaper), or ask
the user to confirm the spend and run it themselves with `! make eval`.
MSG
  exit 2
fi

if printf '%s' "$cmd" | grep -Eq 'deploy\.teardown|deploy/teardown\.py'; then
  cat >&2 <<'MSG'
BLOCKED: teardown destroys the live Railway service, the Neon database, and the
Upstash Redis instance. This is irreversible and takes production down.

Ask the user to confirm explicitly, then have them run it themselves with
`! make deploy.teardown`.
MSG
  exit 2
fi

exit 0
