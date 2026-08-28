.PHONY: dev local local.check test db.migrate db.reset chat install web ui ui.test phase2-runner phase2-restart deploy.provision deploy.ui deploy.smoke deploy.redeploy deploy.logs deploy.teardown eval eval.behaviors

install:
	uv sync

# Bring up Postgres + apply migrations.
dev:
	docker compose up -d
	docker compose exec -T db sh -c 'until pg_isready -U postgres -d maya; do sleep 1; done'
	uv run alembic upgrade head

# Full local stack in one command: Postgres + migrations + SPA build + server.
local:
	bash scripts/dev/run_local.sh

# Same, but boot → probe every endpoint → shut down. Leaves no server running.
local.check:
	bash scripts/dev/run_local.sh --check

db.migrate:
	uv run alembic upgrade head

db.reset:
	uv run alembic downgrade base
	uv run alembic upgrade head

test:
	uv run pytest

# Phase 4 continuous eval (P4.8). Expensive (~$50, real LLM calls + 30-day sims).
# [DECISION] Run on PRs labelled `eval-required` or a weekly cron — NOT every
# push. Runs all personas, judges, and fails if any score regresses > 1.0 vs the
# last recorded run for the same SHA-less baseline.
eval:
	uv run maya evaluate-suite --personas all --days 30 --fail-on-regression

# Targeted behavior assertions only (opt-in eval marker). Cheaper than `eval`.
eval.behaviors:
	uv run pytest -m eval tests/simulator/test_behaviors.py

# Build the SPA into maya/static/. Railway builds via railpack (uv + Procfile)
# with no build-time hook, so Node never runs on the server — the bundle is built
# here and committed.
ui:
	cd frontend && npm ci && npm run build

ui.test:
	cd frontend && npm run test

chat:
	uv run maya chat

web:
	uv run maya web

phase2-runner:
	uv run python -m tests.phase2_runner.server

phase2-restart:
	bash restart_runner.sh

deploy.provision:
	bash scripts/deploy/provision.sh

# Frontend-only deploy: build the SPA and ship it. No migrations, no env writes.
deploy.ui:
	bash scripts/deploy/deploy_frontend.sh

deploy.smoke:
	bash scripts/deploy/with-railway-env.sh sh -c 'DATABASE_URL="$$(uv run python scripts/deploy/asyncpg_url.py)" uv run python scripts/smoke_test.py'

deploy.redeploy:
	bash scripts/deploy/with-railway-env.sh railway up --service maya-core --detach

deploy.logs:
	bash scripts/deploy/with-railway-env.sh railway logs

deploy.teardown:
	uv run python scripts/deploy/teardown.py
