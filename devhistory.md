# Dev history

A running log of work that is worth remembering beyond the diff — measurements that cost real
money to produce, root causes that were not where they looked, and decisions whose reasoning would
otherwise evaporate. The commit list itself lives in git; this file is the *why*.

---

## 2026-08-29 — TLS verification was off, and tooling to stop re-deriving the same context

Session goal was Claude Code tooling, not a bug hunt. The bug was found by asking mypy why it had
7 standing errors — two of which turned out to be the type checker objecting to the mechanism of a
real security bug rather than to its consequences.

### 1. `verify=False` had been shipping as "honor our custom cert bundle"

`maya/__init__.py` monkeypatched `httpx.Client.__init__` and `httpx.AsyncClient.__init__` at import
time, under this comment:

> Patch httpx SSL globally so OpenAI/Mem0 honor our custom cert bundle.

The body did the opposite:

```python
_CERT = _os.environ.get("SSL_CERT_FILE")
if _CERT and _os.path.exists(_CERT):
    def _patched_sync(self, *args, **kwargs):
        kwargs["verify"] = False        # ← _CERT is never passed to httpx
```

`_CERT` was only ever a **trigger condition**. It was never handed to httpx as a trust store. So
whenever `SSL_CERT_FILE` pointed at a file that existed, every httpx client the app built — xAI,
OpenAI, mem0, Telegram — ran with certificate verification disabled.

**Measured, not inferred.** Reproducing the old patch verbatim and probing badssl.com:

| endpoint | old patch | after `66b1e6e` |
|---|---|---|
| `self-signed.badssl.com` | **ACCEPTED 200** | rejected |
| `expired.badssl.com` | **ACCEPTED 200** | rejected |
| `wrong.host.badssl.com` | **ACCEPTED 200** | rejected |
| `api.x.ai/v1/models` | 401 | 401 |
| `api.openai.com/v1/models` | 401 | 401 |

An expired certificate and a hostname mismatch both sailed through. The real providers still
answer after the fix, so nothing was traded away for it.

**Scope — local dev only, but always on.**

- Production was never affected. `provision_railway.sh` sets exactly ten service variables
  (`DATABASE_URL`, `REDIS_URL`, `XAI_API_KEY`, `OPENAI_API_KEY`, `ENVIRONMENT`, `LITELLM_LOG`, and
  the four optional Anthropic/Telegram ones). `SSL_CERT_FILE` is not among them, so the guard was
  false on Railway and the patch never installed.
- Locally it was live on **every** run: `~/.zshrc:8` exports
  `SSL_CERT_FILE=~/.certs/all-certs.pem`, and that bundle exists (326 KB). Every `make chat`,
  `make web`, and test run started from that shell had verification off.

**Fix** (`66b1e6e`): delete the patch, call `truststore.inject_into_ssl()` — which is what all five
`scripts/deploy/*.py`, `scripts/smoke_test.py` and `tools/grokbench/bench.py` already did.
`truststore` was already a dependency. It reads the OS trust store, so the Zscaler root is honoured
*with verification left on*. Wrapped in `try/except` so a truststore failure degrades to certifi
with verification still enabled — it fails closed, not open.

**General lesson:** the comment was not merely stale, it asserted the inverse of the code. It
shipped in the initial commit (`e39844a`, 2026-06-23) and was read past for just over two months.
When a comment describes a security property, verify the property, not the comment. The two-line
mypy complaint (`Cannot assign to a method`) was pointing at this the whole time and had been
living in the "known noise" pile.

### 2. Why mypy had 7 standing errors, and why that mattered

7 errors from 4 causes, none of them runtime bugs, all pre-existing (`535066c`):

- `response_length.py:32` — the ignore was written `[arg-type]` but mypy reports `[call-overload]`
  for `int(level)` where `level: object`. With `warn_unused_ignores` on, one typo produced **two**
  errors: the unused ignore, plus the real error left unsuppressed.
- `memory/service.py`, `cli.py` — `rowcount` is on `CursorResult`, not the `Result` that
  `session.execute()` is typed to return. Correct at runtime for DML.
- `cli.py` — `events` rebound from `List[RelationshipEvent]` to a list of tuples.
- `__init__.py` — §1.

The point of clearing them is not tidiness. A checker that is red on arrival gets skipped, which is
exactly how §1 survived. Zero is now enforced by a Stop hook, so the next non-zero is something
just introduced.

### 3. `maya show-prompt` — acting on the 2026-08-28 lesson

The previous entry ended with "dump the fully-assembled prompt before theorising", but no command
did that, so the next investigation would have re-derived it by hand. `feaa8db` adds one.

Design decisions that are not obvious from the diff:

- **`--moment default` is the default, and it means `default_moment()`.** That is what the live
  critical path actually sends: `_prepare` builds the prompt with a neutral moment so the main call
  can start immediately, and the real classification lands in post-processing. A dump that showed
  the *classified* moment would show a prompt the model never received. `--moment auto` runs the
  real analyzer; any type can be forced.
- **Read-only.** `_prepare` saves the user message as part of its gather; the dump must not, or
  inspecting a bug would mutate the conversation being inspected.
- **`build_phase3` gained `enforce_budget: bool = True`.** An over-budget prompt is precisely the
  one worth looking at, so raising instead of rendering would defeat the command.
- **The source map has a tripwire.** `_sources` hand-maps all 21 placeholders to their origin, so it
  would rot silently. `test_source_map_covers_every_template_field` parses the template's
  `{placeholders}` and asserts the map covers exactly that set.

Verified against the live local companion: `pacing_directive` reads `ON` for chitchat and
`off — intimate is in NO_PACING_MOMENTS` when forced intimate, matching its presence and absence in
the assembled text. The `dc50162` investigation is now one command.

### 4. Hooks, and one blind spot

`c6d7e2f` moves the inline ruff hook into `.claude/hooks/post_edit.sh` and adds path-keyed
reminders, a spend guard, and a pre-stop gate. Reasoning worth keeping:

- **Reminders beat CLAUDE.md for cross-file rituals.** `058139a` trimmed CLAUDE.md precisely because
  always-loaded guidance competes for attention. A `PostToolUse` reminder keyed on
  `maya/web.py` costs nothing until that file is touched.
- **The Stop gate runs tests + mypy but *not* ruff.** `tests/phase2_runner/server.py:105` has a
  standing `F841`, so `ruff check` over the whole repo is red on arrival — see §2 for why that
  disqualifies it as a gate. `ruff check maya` alone is clean; the blocker is one unused variable
  in a test runner.
- **The spend guard matches command text, so writing *about* a blocked command trips it.** This was
  found the direct way: the commit message for `c6d7e2f` described the teardown target and was
  blocked by its own hook. Workaround is `git commit -F <file>`. Left as-is — making the matcher
  context-aware is not worth the complexity for a rare false positive with a one-step escape.

### 5. Open threads

- **mem0 is still the dominant critical-path leg** (carried over from 2026-08-28 §6 — untouched
  this session).
- **`ruff check` cannot join the Stop gate** until `tests/phase2_runner/server.py:105` is cleared.
  One-line deletion, deliberately left out of this session's commits to keep them scoped.
- **4 commits are unpushed** to `github.com/meiridan/aips` — this session's. `origin/main` is at
  `058139a`, so the 2026-08-28 backlog has since been pushed and that entry's "13 commits are
  unpushed" note is now historical. Nothing from either session has been *deployed*: production
  still predates the `74e0291` model switch. The `66b1e6e` TLS fix is local-dev-only in effect, so
  it is not a production exposure.

---

## 2026-08-28 — wizard commit, local stack, Grok latency, and a self-contradicting prompt

### 1. Committing the creation wizard

A ~30-file uncommitted tree (companion creation wizard, persona spec, Hebrew SPA) went in as seven
logical commits, `4c68147`..`13a5dea`, rather than one dump.

Two things worth knowing:

- **`prompt_builder.py` carried two unrelated changes** — Grok-aware token counting and the reply
  language directive. They belonged in different commits, so the file was split by writing an
  intermediate version containing only the first change, verifying it green, committing, then
  restoring the full version for the second commit. Both intermediate states pass the suite.
- **`.claude/settings.local.json` and `.serena/` are gitignored**, not committed — they hold
  machine-local permission grants and local entity ids. `.claude/settings.json` (the ruff
  PostToolUse hook) *is* committed, since it applies to anyone working in the repo.

### 2. Standing the stack up locally

`scripts/dev/run_local.sh --no-reload` was dead on arrival:

```
scripts/dev/run_local.sh: line 174: RELOAD_ARGS[@]: unbound variable
```

macOS ships **bash 3.2**, where an empty array counts as *unset* under `set -u`. `--no-reload` sets
`RELOAD_ARGS=()`, so expanding it was fatal. Fixed in `e60d346` with the `${RELOAD_ARGS[@]+"..."}`
guard. Any future empty-array expansion in these scripts needs the same treatment.

Also confirmed: rebuilding the SPA produced **byte-identical asset hashes** to the committed
bundle, so `maya/static/` is reproducible from `frontend/` and the "build output is committed"
arrangement is honest.

### 3. The Grok latency investigation

A real web turn logged `ttft_ms=6791`, with the main call at `latency_ms=7142` for **16 output
tokens**. That number made no sense, and the reason it made no sense is itself the first finding:

> **litellm folds xAI's `reasoning_tokens` into `completion_tokens`**
> (`litellm/llms/xai/chat/transformation.py:261`).
>
> So "16 output tokens" was never 16 visible tokens, and the app's own logs could not show where
> the time went. Reading `usage.completion_tokens_details.reasoning_tokens` off the raw API is the
> only way to see the split.

That motivated `tools/grokbench/` — a small CLI that talks to `https://api.x.ai/v1` over raw httpx,
so xAI's latency can be separated from litellm, from the local Zscaler MITM proxy, and from prompt
size. See `tools/grokbench/README.md`.

**Measurements** — all on the same 22-message Hebrew prompt (~2381 prompt tokens), 2–3 runs each:

| config | TTFT median | total median | reasoning tokens |
|---|---|---|---|
| `grok-4.20-0309-non-reasoning` | **864 ms** | 1949 ms | 0 |
| `grok-4.5`, `reasoning_effort=low` | **4372 ms** | 6278 ms | 153–188 |
| `grok-4.3`, `reasoning_effort=low` | 5288 ms | 5827 ms | 401–480 |
| `grok-4.6`, `reasoning_effort=low` | 5606 ms | 8167 ms | ~250 |
| `grok-4.20-0309-reasoning` | 22389 ms | 23167 ms | 1441–2100 |
| `grok-4.6`, param omitted | **35148 ms** | 36576 ms | 1542–2161 |

**What that settles:**

- **The latency is reasoning tokens**, generated before the first visible character. Not
  infrastructure.
- **Zscaler is not the problem.** TLS handshake measures 100–290 ms; cold-vs-warm connection delta
  is ~600 ms TTFT.
- **litellm overhead is secondary** — roughly +480 ms TTFT, inside the run-to-run noise band at
  n=3, so treat it as an upper bound.
- **`DEFAULT_REASONING_EFFORT = "low"` is load-bearing.** Omitting the parameter makes grok-4.6
  **5–8× slower**. Do not "simplify" that gate away.
- **`low` is the floor.** `"minimal"` is accepted without a 400 but produced *more* reasoning than
  `low`, so xAI ignores unknown values.
- **`grok-4.20-0309-reasoning` is unusable on the critical path** — it rejects `reasoningEffort`
  outright (`"Model grok-4.20-0309-reasoning does not support parameter reasoningEffort"`), so its
  ~1700 reasoning tokens cannot be capped.

**Outcome:** the main tier primary moved `grok-4.6` → `grok-4.5` (`74e0291`). Measured live
afterwards at `ttft_ms` 2605–2833, roughly half the old figure. grok-4.6 was deliberately *not*
kept as a fallback — the chain is cross-provider (grok → GPT → Claude) so a single xAI outage moves
off the provider instead of retrying it twice.

The non-reasoning model stays right for the `fast` tier and wrong for `main`: on the quality A/B it
opened two consecutive replies with an identical sentence and closed both on a stock question,
where grok-4.5 and grok-4.6 both reached unprompted into the backstory.

### 4. Why the companion refused sexual content

The app is NSFW-capable by design, but the companion kept deflecting. **There is no content filter
in the codebase** — the cause was a stack of configuration plus one real prompt bug.

Configuration, all of it injected verbatim into the system prompt:

- relationship state was `Day 0 | Stage: curious | Intimacy: 1/10 | Trust: 1/10`
- `persona_spec.personality` was `romantic`, not the catalog's `nympho`
  (`maya/companions/catalog.py:303`, `"openly sexual and uninhibited"`)
- the genesis-written backstory had been generated under the old persona and pulled the other way

But even with all of that corrected — moment classified `intimate`, priority `passion`, guidance
`"Match his desire and tone"`, intimacy 10/10 — she still deflected. **The prompt was contradicting
itself.** `PHASE3_SYSTEM_TEMPLATE`'s last bullet shipped on *every* turn:

> Do not pivot straight to playfulness or intimacy without a brief acknowledgment.

That sat four lines below the moment's own instruction to engage. The refusal half won, and the
replies quoted it back nearly verbatim (*"ככה ישר זה מרגיש לי מהיר"*).

Fixed in `dc50162` by making the guard conditional rather than deleting it — the rule does real
work stopping a crisis turn from being answered with a tonal pivot. `NO_PACING_MOMENTS` exempts
`intimate` and `playful_banter`, the two moments where the user has already set the tone. Every
other moment still gets it.

**A test was lying.** The Bug 5 regression test covering this guard was passing *vacuously*: its
fixture moment is `playful_banter` (now exempt), and it only asserted that the words
"vulnerable"/"honour" appeared — never the directive itself. It would have stayed green with the
line deleted entirely. Now pinned to an ordinary moment and asserting the actual text, with tests
on both sides of the exemption.

**General lesson:** when a model behaves against its instructions, dump the fully-assembled prompt
before theorising. `build_phase3` composes from six sources and two of them disagreed; that is
invisible from any single file.

### 5. Local database state (not a product path)

The live local companion was edited directly — relationship row via SQL, persona via a script that
goes through the real `PersonaSpec` + `personality_blob` so the JSON matches what the wizard would
write, then a genesis re-run to regenerate the backstory against the new spec.

Two gotchas for anyone doing this again:

- **`runtime_cache` holds the Companion row per-process** (`maya/runtime_cache.py:27`). Any persona
  write needs a server restart, or the running uvicorn keeps serving the old personality. The CLI
  starts fresh each invocation, so it is unaffected. Emotional and relationship state are
  deliberately *not* cached and go live immediately.
- **The stage machine reacts on its own.** Setting `intimacy=10, days_known=30` caused
  `dating → in_love → committed` to fire over subsequent turns via `transitions.py`.

### 6. Open threads

- **mem0 is now the dominant critical-path leg.** After the model switch, a turn showed
  `memory_ms=3704` of `prepare_ms=3920` — the memory search now costs more than the LLM call. This
  is the next latency target.
- **The NSFW configuration has no product surface.** Everything in §5 was raw SQL. The wizard
  exposes `personality` and `extra_details`, but the intimacy grind
  (`transitions.py`: 20 interactions and intimacy ≥ 3 just to reach `flirting`, with intimacy
  moving +1 per intense moment) may be tuned wrong for a single-user app where the user is the one
  asking.
- **13 commits are unpushed** to `github.com/meiridan/aips`, and nothing from this session has been
  deployed.
