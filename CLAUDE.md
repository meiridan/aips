# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Maya Core: a companion/romantic chatbot (intentional NSFW-capable roleplay scope — not a bug, don't hedge on related code) with a conversation orchestrator, memory layer (`mem0ai`), and emotional/relationship modeling. Two channels share one app: Telegram bot (`maya/telegram/`) and a web UI + WebSocket (`maya/web.py`). Single-package Python repo (`maya-core`), no monorepo structure.

A change to the reply flow usually needs matching updates in **both** `maya/telegram/service.py` and `maya/web.py`, plus their unit tests — they share the orchestrator's critical path but are separate entry points.

The web UI is a Hebrew/RTL React SPA in `frontend/`, built into `maya/static/` and served by FastAPI. It shows a 6-step companion-creation wizard until the companion is onboarded, then the chat screen. Every wizard option lives once in `maya/companions/catalog.py` (Hebrew label + English prompt fragment) and is validated by `maya/companions/persona_spec.py` — add options there, never in the frontend.

## Commands

- `uv sync` — install deps (package manager is **uv**, not pip/poetry)
- `make dev` — docker compose up (Postgres+pgvector) + `alembic upgrade head`
- `make test` / `uv run pytest` — unit + integration tests. Eval tests are excluded by default (`addopts = -m 'not eval'` in pyproject) because they make real paid LLM calls; opt in with `uv run pytest -m eval` or `make eval.behaviors`.
- `make eval` — full paid eval suite (~$50, real LLM calls + 30-day sims). Do not run casually; intended for `eval-required`-labeled PRs or weekly cron, not every push.
- `make chat` / `make web` — run the CLI REPL / web server locally
- `make ui` — build the SPA (`frontend/` → `maya/static/`). **The build output is committed**: Railway's railpack build has no build-time hook, so Node never runs on the server. Rebuild and commit whenever `frontend/` changes. `make ui.test` runs the frontend unit tests.
- `make db.migrate` / `make db.reset` — Alembic migrations (`maya/db/migrations`)
- `uv run ruff check` / `uv run ruff format` — lint/format (line-length 100, py311, isort first-party = `maya`; no black)
- `uv run mypy` — type check (pydantic plugin enabled; `tests/*` exempt from `disallow_untyped_defs`)

No CI (`.github/workflows`) exists — tests/lint are run locally, not gated automatically.

## Database

Postgres + pgvector via SQLAlchemy async (`asyncpg` driver) + Alembic. Pool in `maya/db/session.py` is explicitly tuned for **Neon serverless** (scale-to-zero closes idle connections): `pool_pre_ping=True`, `pool_size=10`, `max_overflow=5`, `pool_recycle=1800`, plus a startup warmup that pre-opens 5 connections. Keep these Neon-specific settings in mind before "simplifying" the pool config.

## LLM integration

Routed through `litellm` with an explicit fallback chain: Grok (`XAI_API_KEY`) → GPT (`OPENAI_API_KEY`, also used for embeddings) → Claude (`ANTHROPIC_API_KEY`, optional secondary fallback). Explicit request timeouts (30s/45s) exist specifically to fail over faster through this chain — don't remove them without preserving that intent.

## Deployment

Deploys via `make deploy.provision` (Railway + Neon + Upstash Redis, `scripts/deploy/`). One uvicorn process (`maya.web:app`) serves both channels. Non-obvious gotchas:
- Local dev machine has a **Zscaler MITM proxy**; Python uses `truststore.inject_into_ssl()` and the Railway CLI needs `SSL_CERT_FILE` pointed at the exported Zscaler root CA (handled by `provision.sh`) — certifi alone fails here.
- Railway auth uses `RAILWAY_API_TOKEN`, not `RAILWAY_TOKEN` (deploy scripts remap it from `.deploy.env`).
- Railway builds via railpack (auto-detects uv + Procfile); there's no build-time hook, so migrations run **locally** against Neon during provisioning, not on the server.
- `DATABASE_URL` needs `postgresql+asyncpg://...?ssl=require`; `scripts/deploy/asyncpg_url.py` converts Neon's raw URL to this form.

## Workflow

Solo dev, commits go directly to `main` — no PR requirement.

## Workflow Orchestration

### 1. Plan Mode Default
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately - don't keep pushing
- Use plan mode for verification steps, not just building
- Write detailed specs upfront to reduce ambiguity

### 2. Subagent Strategy
- Use subagents liberally to keep main context window clean
- Offload research, exploration, and parallel analysis to subagents
- For complex problems, throw more compute at it via subagents
- One tack per subagent for focused execution

### 3. Self-Improvement Loop
- After ANY correction from the user: update `tasks/lessons.md` with the pattern
- Write rules for yourself that prevent the same mistake
- Ruthlessly iterate on these lessons until mistake rate drops
- Review lessons at session start for relevant project

### 4. Verification Before Done
- Never mark a task complete without proving it works
- Diff behavior between main and your changes when relevant
- Ask yourself: "Would a staff engineer approve this?"
- Run tests, check logs, demonstrate correctness

### 5. Demand Elegance (Balanced)
- For non-trivial changes: pause and ask "is there a more elegant way?"
- If a fix feels hacky: "Knowing everything I know now, implement the elegant solution"
- Skip this for simple, obvious fixes - don't over-engineer
- Challenge your own work before presenting it

### 6. Autonomous Bug Fixing
- When given a bug report: just fix it. Don't ask for hand-holding
- Point at logs, errors, failing tests - then resolve them
- Zero context switching required from the user
- Go fix failing CI tests without being told how

## Task Management

1. **Plan First**: Write plan to `tasks/todo.md` with checkable items
2. **Verify Plan**: Check in before starting implementation
3. **Track Progress**: Mark items complete as you go
4. **Explain Changes**: High-level summary at each step
5. **Document Results**: Add review section to `tasks/todo.md`
6. **Capture Lessons**: Update `tasks/lessons.md` after corrections

## Core Principles

- **Simplicity First**: Make every change as simple as possible. Impact minimal code.
- **No Laziness**: Find root causes. No temporary fixes. Senior developer standards.
- **Minimat Impact**: Changes should only touch what's necessary. Avoid introducing bugs.