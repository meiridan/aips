.PHONY: dev test db.migrate db.reset chat install web phase2-runner phase2-restart deploy.provision deploy.smoke deploy.redeploy deploy.logs deploy.teardown

install:
	uv sync

# Bring up Postgres + apply migrations.
dev:
	docker compose up -d
	docker compose exec -T db sh -c 'until pg_isready -U postgres -d maya; do sleep 1; done'
	uv run alembic upgrade head

db.migrate:
	uv run alembic upgrade head

db.reset:
	uv run alembic downgrade base
	uv run alembic upgrade head

test:
	uv run pytest

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

deploy.smoke:
	bash scripts/deploy/with-railway-env.sh sh -c 'DATABASE_URL="$$(uv run python scripts/deploy/asyncpg_url.py)" uv run python scripts/smoke_test.py'

deploy.redeploy:
	bash scripts/deploy/with-railway-env.sh railway up --service maya-core --detach

deploy.logs:
	bash scripts/deploy/with-railway-env.sh railway logs

deploy.teardown:
	uv run python scripts/deploy/teardown.py
