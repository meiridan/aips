# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Maya Core: a companion/romantic chatbot (intentional NSFW-capable roleplay scope — not a bug, don't hedge on related code) with a conversation orchestrator, memory layer (`mem0ai`), and emotional/relationship modeling. Two channels share one app: Telegram bot (`maya/telegram/`) and a web UI + WebSocket (`maya/web.py`). Single-package Python repo (`maya-core`), no monorepo structure.

**The app is multi-user.** It used to be single-user — one shared Maya resolved by `resolve_singleton()` — and that is gone. Identity now comes from the channel: a session cookie on the web (`maya/auth/`), `users.telegram_chat_id` on Telegram, `MAYA_USER_ID` in the CLI. Each account has its own companion, messages and memories. `maya/companions/singleton.py` still holds the resolution logic (`resolve_for_user`, `resolve_by_telegram_chat`) despite the now-misleading module name.

A change to the reply flow usually needs matching updates in **both** `maya/telegram/service.py` and `maya/web.py`, plus their unit tests — they share the orchestrator's critical path but are separate entry points. That now includes the entitlement check: both gate on `entitlements.quota_exceeded` before calling the orchestrator.

The web UI is a Hebrew/RTL React SPA in `frontend/`, built into `maya/static/` and served by FastAPI. It shows a 6-step companion-creation wizard until the companion is onboarded, then the chat screen. Every wizard option lives once in `maya/companions/catalog.py` (Hebrew label + English prompt fragment) and is validated by `maya/companions/persona_spec.py` — add options there, never in the frontend.

## Auth & billing

- **Sessions** are opaque, stored in Postgres (`sessions`), only the SHA-256 of the cookie value is kept. Not JWT — a password reset revokes every session in one statement. Cookie: `maya_session`, HttpOnly, SameSite=Lax, Secure off only when `ENVIRONMENT=local`.
- **Passwords** use stdlib `hashlib.scrypt` (`maya/auth/passwords.py`). It needs an explicit `maxmem` — the default is a 32 MiB ceiling and these parameters need exactly 32 MiB, so the call raises without it.
- **Google sign-in** is hand-rolled over `httpx` (`maya/auth/google.py`): Authorization Code + PKCE, profile read from Google's userinfo endpoint. No `google-auth`/`pyjwt` — the code is exchanged server-to-server, so there is no third-party JWT to verify.
- **`/ws` authenticates from the handshake cookie.** On no session it accepts and then closes with **4401**; a refused handshake would reach the browser with no readable code, and the SPA uses 4401 to stop its 2s reconnect loop.
- **Entitlement is decided only by `maya/billing/entitlements.py`**, reading the `subscriptions` row. That row is written *only* by the Stripe webhook. Never let a client-supplied plan id influence access.
- **Adding a plan** means editing `maya/billing/plans.py` (and its `STRIPE_PRICE_*` env var) — never the frontend, the same rule as `companions/catalog.py`.
- **Hebrew UI strings** (including every auth and billing string) live in `UI_STRINGS` in `maya/companions/catalog.py` and ride the public `GET /api/catalog`, so the login screen can render before anyone is signed in.
- **`DEV_AUTOLOGIN=1` skips the login screen** and serves every unauthenticated request (HTTP *and* `/ws`) as the fixed `dev@local.test` account. `maya/auth/deps.dev_autologin_enabled()` also requires `ENVIRONMENT=local`, so the flag is inert in a deployed instance. `scripts/dev/run_local.sh` sets it by default; pass `--login` for the real screen.
- `uv run maya claim-account --email <e>` attaches credentials to an existing user row. **Run it before an account-aware build serves traffic**, or the first signup creates a second, empty companion and the original conversation is stranded.

## Commands

- `uv sync` — install deps (package manager is **uv**, not pip/poetry)
- `make dev` — docker compose up (Postgres+pgvector) + `alembic upgrade head`
- `make test` / `uv run pytest` — unit + integration tests. Eval tests are excluded by default (`addopts = -m 'not eval'` in pyproject) because they make real paid LLM calls; opt in with `uv run pytest -m eval` or `make eval.behaviors`.
- `make eval` — full paid eval suite (~$50, real LLM calls + 30-day sims). Do not run casually; intended for `eval-required`-labeled PRs or weekly cron, not every push.
- `make chat` / `make web` — run the CLI REPL / web server locally
- `uv run maya show-prompt "<msg>"` — dump the fully-assembled Phase-3 system prompt with per-field source attribution (read-only; saves nothing). `build_phase3` composes from six sources, so when the companion behaves against its instructions, **dump the prompt before theorising** — the contradiction is never visible in a single file. `--moment intimate` forces a moment, `--moment auto` runs the real analyzer (paid), default is what the live critical path actually sends.
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

Railway + Neon + Upstash Redis. Commands and the full gotcha list (Zscaler CA, `RAILWAY_API_TOKEN`, no build-time hook, asyncpg URL form) live in the `deploy-maya` skill — invoke `/deploy-maya` before touching deploy.

## Workflow

Solo dev, commits go directly to `main` — no PR requirement.
