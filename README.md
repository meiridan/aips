# Maya Core

Chat orchestrator + memory layer + Grok integration (CLI-first, no web layer).
See `MAYA_CORE_SPEC.md` for the full spec.

## Phase 1 — Foundation & Dumb Chat

Working repo skeleton, Postgres+pgvector, an LLM gateway with a Grok→GPT→Claude
fallback chain, and a CLI for stateless conversation. **No memory yet.**

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- Docker (for Postgres + pgvector)

### Setup

```bash
cp .env.example .env        # then fill in XAI_API_KEY / OPENAI_API_KEY
uv sync                     # install deps + create venv
make dev                    # start Postgres, apply migrations
```

### Usage

```bash
# Create a test user + companion (prints export line)
uv run maya seed --user-name "David" --user-description "35yo developer, lonely, Tel Aviv"
export MAYA_USER_ID=...  MAYA_COMPANION_ID=...

make chat                   # interactive REPL with Maya
uv run maya state           # companion snapshot
uv run maya history --limit 50
uv run maya reset           # wipe messages, keep user/companion
```

### Tests

```bash
make test                   # unit tests (LLM mocked, no DB/network needed)
```

### Make targets

| Target | Action |
|---|---|
| `make install` | `uv sync` |
| `make dev` | Postgres up + `alembic upgrade head` |
| `make db.migrate` | `alembic upgrade head` |
| `make db.reset` | downgrade to base + upgrade |
| `make test` | `uv run pytest` |
| `make chat` | open the chat REPL |
