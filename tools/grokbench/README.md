# grokbench

A small CLI that talks to `https://api.x.ai/v1` over raw HTTP, so xAI's latency can be measured
without the Maya stack in the way. Diagnostic only — nothing in `maya/` imports it, and
`.railwayignore` keeps it out of the deploy.

It shares the repo's `.env` and uv venv, so there is nothing to install.

## Why it exists

A real web turn took 7.1s on one `grok-4.6` call that litellm logged as 16 output tokens. From
inside the app there was no way to separate four candidate causes: xAI itself, litellm's
overhead, the Zscaler MITM proxy's TLS handshake, or the ~2000-token Hebrew prompt. This tool
measures each one on its own.

## Commands

```bash
uv run python tools/grokbench/bench.py models          # what the key can reach. free.
uv run python tools/grokbench/bench.py tokenize        # true Grok token count of the fixture
uv run python tools/grokbench/bench.py run --help      # the bench
```

### `run`

```bash
# the floor: a 3-word prompt
uv run python tools/grokbench/bench.py run --preset tiny -n 3

# the real thing: the captured 22-message Hebrew prompt
uv run python tools/grokbench/bench.py run --preset maya -n 3

# what reasoning costs
uv run python tools/grokbench/bench.py run --preset maya --reasoning-effort none -n 3

# what the Zscaler TLS handshake costs (fresh connection every run)
uv run python tools/grokbench/bench.py run --preset maya --cold -n 3

# what litellm costs on top of raw HTTP
uv run python tools/grokbench/bench.py run --preset maya --via-litellm -n 3

# sweep models in one go
uv run python tools/grokbench/bench.py run -m grok-4.6 -m grok-4.5 -m grok-4.20-0309-non-reasoning
```

Each call is paid. `-n 3` at the default 800 max tokens keeps a full sweep to cents.

## Reading the output

```
connection probe: tcp 3 ms · tls handshake 146 ms
messages: 22  ·  runs: 3  ·  stream: True  ·  cold: False

  grok-4.6  (raw, warm)
    #    ttft_ms  total_ms   tok/s   prompt  out  reasoning
    1     4886     6167     6.8     2381    42        217
```

| column | meaning |
|---|---|
| `connection probe` | one fresh TCP connect and TLS handshake, measured before any request. This is the Zscaler line item |
| `ttft_ms` | time to the first **visible** token. Reasoning happens before this |
| `total_ms` | first byte sent to last token received |
| `tok/s` | visible output tokens per second over the whole call |
| `prompt` | tokens xAI actually charged for the request |
| `out` | visible completion tokens |
| `reasoning` | hidden reasoning tokens. **Read as untouched by `out`** — the raw API keeps them separate |

That last row matters most. litellm folds reasoning into `completion_tokens`
(`litellm/llms/xai/chat/transformation.py:261`), which is why Maya's own logs showed "16 output
tokens" for a 7-second call and made the latency look inexplicable. Raw, the split is visible:
most of the wall clock is reasoning tokens generated before the first visible character.

Note that `--preset tiny` still reports a few hundred prompt tokens. The model carries a
server-side system prompt of its own; a "3-word request" is never actually three tokens.

## The maya fixture

`prompts/maya_he.json` is a 22-message Hebrew conversation built by the real
`maya.conversation.prompt_builder.build_phase3`, so it has the same shape as a live turn:
Phase-3 system block, 15 memories, 2 commitments, 20 messages of history. It bills at ~2381
prompt tokens against the observed ~2005 of a live turn.

Regenerate it with `uv run python tools/grokbench/capture_fixture.py` after changing the
prompt template. Editing the JSON by hand is fine too — it is just a message list.

## `tokenize`

`POST /v1/tokenize-text` returns the true Grok token count, which is where the Hebrew scaling
factors in `maya/conversation/prompt_builder.py` (`_GROK_BASE_FACTOR`, `_GROK_HEBREW_FACTOR`)
came from. Running it prints the guard's estimate alongside the real count and says whether the
guard is still over-estimating — which is the property the budget check depends on.

```
chars 4464  ·  grok tokens 1670  ·  our guard estimates 1793
guard/actual ratio 1.074 — safe (over-estimates)
```
