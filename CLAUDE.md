# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Maya Core: a companion/romantic chatbot (intentional NSFW-capable roleplay scope — not a bug, don't hedge on related code) with a conversation orchestrator, memory layer (`mem0ai`), and emotional/relationship modeling. Two channels share one app: Telegram bot (`maya/telegram/`) and a web UI + WebSocket (`maya/web.py`). Single-package Python repo (`maya-core`), no monorepo structure.

**The app is multi-user.** It used to be single-user — one shared Maya resolved by `resolve_singleton()` — and that is gone. Identity now comes from the channel: a session cookie on the web (`maya/auth/`), `users.telegram_chat_id` on Telegram, `MAYA_USER_ID` in the CLI. Each account has its own companion, messages and memories. `maya/companions/singleton.py` still holds the resolution logic (`resolve_for_user`, `resolve_by_telegram_chat`) despite the now-misleading module name.

A change to the reply flow usually needs matching updates in **both** `maya/telegram/service.py` and `maya/web.py`, plus their unit tests — they share the orchestrator's critical path but are separate entry points. That now includes the entitlement check: both gate on `entitlements.quota_exceeded` before calling the orchestrator.

The web UI is a Hebrew/RTL React SPA in `frontend/`, built into `maya/static/` and served by FastAPI. It shows a 6-step companion-creation wizard until the companion is onboarded, then the chat screen. Every wizard option lives once in `maya/companions/catalog.py` (Hebrew label + English prompt fragment) and is validated by `maya/companions/persona_spec.py` — add options there, never in the frontend.

## Group chat (Maya + Lila)

- `/group` in the SPA, `GET /api/group` + `/ws/group` on the server, `GroupOrchestrator` in `maya/conversation/group.py`. It reuses the `Orchestrator`'s services but is a **third entry point**: a change to the reply flow (entitlement gate, context gathering, post-processing) usually needs a matching change there too. Telegram has no group chat.
- **Transcripts are per conversation, state is per companion.** Every transcript read filters on `messages.conversation_id` (`conversations` + `conversation_members`) — never on `messages.companion_id`, which also tags her lines in group rooms and would leak them into her solo chat. A solo chat is a one-member room created lazily by `rooms.solo_conversation_id`. Memories, emotions, relationship and commitments stay keyed by companion, so Maya is the same person in both rooms.
- **Companions have a `slot`.** `primary` is the account's own companion and the only one `resolve_for_user` returns; a group partner uses her catalog id (`lila`). Partners live in `GROUP_PARTNERS` in `catalog.py` (not in the gallery). `singleton.resolve_group` creates her and runs her genesis once — one paid main-tier call — with her opener landing in the room.
- **Routing** (`conversation/addressing.py`): an explicit UI target wins; else names at the start of the message pick the addressees; else everyone. Names that are also Hebrew words (`COMMON_WORD_NAMES`: "לילה" is *night*) only count with punctuation, `@`, another name, or alone.
- **Floor control**: addressees speak sequentially (the second one's prompt holds the first reply), then the room's **talk mode** decides what follows. *Moderated* (default): they alternate until `GROUP_MODERATED_MIN_MESSAGES` (3), then a fast-tier `Director` may add one more up to `GROUP_MAX_AI_MESSAGES_PER_TURN` (4). *Free*: they alternate with no director until the user writes or `GROUP_FREE_TALK_MAX_MESSAGES` (20). Always: no speaker twice in a row, near-repeats end the turn.
- **Room settings** (`conversation/group_settings.py`, stored in `conversations.settings`): talk mode plus the room's own reply length (short = 1–3 sentences; independent of the 1:1 `companions.response_length`). The SPA changes them over `/ws/group` as `{type: "settings", ...}`; the socket shares one live `GroupSettings` with the running turn, so a toggle takes effect before the next speaker. A new user message cancels speakers who haven't started. `ReplyGuard` cuts a streamed reply where she starts writing someone else's line.
- **Prompt**: `GROUP_SYSTEM_TEMPLATE` is concatenated from the same section constants as `PHASE3_SYSTEM_TEMPLATE` — edit the sections, never a copy. Other speakers reach her as `user` turns prefixed `[name]:`. Dump it with `uv run maya show-prompt --group --speaker lila "<msg>"`.
- A wizard re-creation of the primary companion clears every group room she is in (`rooms.wipe_group_rooms`).

## Auth & billing

- **The login flow is currently switched off.** `SINGLE_USER` defaults to `True` (`maya/config.py`), and `maya/auth/deps.single_user_enabled()` makes `optional_user` / `user_id_from_websocket` resolve every request — HTTP *and* `/ws`, local *and* deployed — to one account before any cookie is read. So the SPA never renders a login screen (`/api/auth/me` always answers, `auth.single_user` on `GET /api/catalog` hides the logout button) and `quota_exceeded` short-circuits to `False`, because one shared account would otherwise hit the free 30/day cap for everyone. **This leaves the deployed URL open to anyone who has it** — that is the current intent, not an oversight. Everything below describes the real auth stack, which is intact behind `SINGLE_USER=0`.
- **Which account single-user mode lands on**: `MAYA_SINGLE_USER_ID` if set (a `users.id`; `.env` pins the local row), otherwise a passwordless `solo@maya.local` row created on first request. The id is memoized in `maya/auth/deps.py` — call `reset_solo_cache()` after a DB reset. Unlike `DEV_AUTOLOGIN` there is **no** `ENVIRONMENT=local` guard.
- **Tests run with the login flow on**: `tests/conftest._single_user_off` forces `SINGLE_USER=0` for the whole suite, since nothing can be unauthenticated otherwise; `tests/unit/test_single_user.py` opts back in. `run_local.sh --check` exports `SINGLE_USER=0` too, so its 401 probes still mean something.
- **Sessions** are opaque, stored in Postgres (`sessions`), only the SHA-256 of the cookie value is kept. Not JWT — a password reset revokes every session in one statement. Cookie: `maya_session`, HttpOnly, SameSite=Lax, Secure off only when `ENVIRONMENT=local`.
- **Passwords** use stdlib `hashlib.scrypt` (`maya/auth/passwords.py`). It needs an explicit `maxmem` — the default is a 32 MiB ceiling and these parameters need exactly 32 MiB, so the call raises without it.
- **Google sign-in** is hand-rolled over `httpx` (`maya/auth/google.py`): Authorization Code + PKCE, profile read from Google's userinfo endpoint. No `google-auth`/`pyjwt` — the code is exchanged server-to-server, so there is no third-party JWT to verify.
- **`/ws` authenticates from the handshake cookie.** On no session it accepts and then closes with **4401**; a refused handshake would reach the browser with no readable code, and the SPA uses 4401 to stop its 2s reconnect loop.
- **Entitlement is decided only by `maya/billing/entitlements.py`**, reading the `subscriptions` row. That row is written *only* by the Stripe webhook. Never let a client-supplied plan id influence access.
- **Adding a plan** means editing `maya/billing/plans.py` (and its `STRIPE_PRICE_*` env var) — never the frontend, the same rule as `companions/catalog.py`.
- **Hebrew UI strings** (including every auth and billing string) live in `UI_STRINGS` in `maya/companions/catalog.py` and ride the public `GET /api/catalog`, so the login screen can render before anyone is signed in.
- **`DEV_AUTOLOGIN=1` skips the login screen** and serves every unauthenticated request (HTTP *and* `/ws`) as the fixed `dev@local.test` account. `maya/auth/deps.dev_autologin_enabled()` also requires `ENVIRONMENT=local`, so the flag is inert in a deployed instance. `scripts/dev/run_local.sh` sets it by default; pass `--login` for the real screen (which also sets `SINGLE_USER=0`). Largely superseded by `SINGLE_USER` above.
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
