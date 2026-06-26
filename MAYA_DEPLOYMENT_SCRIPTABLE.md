# Maya Core — Scriptable Deployment

**Purpose:** Deploy Maya Core to free-tier cloud with maximum automation. Every step that *can* be a script, *is* a script.
**Stack:** FastAPI/Celery on Railway, Postgres+pgvector on Neon, Redis on Upstash.

---

## 0. What Can and Cannot Be Scripted

The honest breakdown:

| Step | Scriptable? | How |
|---|---|---|
| Create Neon project + DB | ✅ Yes | Neon API / `neonctl` |
| Enable pgvector | ✅ Yes | SQL over connection |
| Create Upstash Redis | ✅ Yes | Upstash REST API |
| Provision Railway services | ✅ Yes | Railway CLI |
| Set env vars on Railway | ✅ Yes | Railway CLI |
| Deploy | ✅ Yes | Railway CLI / git push |
| Run migrations | ✅ Yes | build hook |
| Smoke test | ✅ Yes | Python script |
| **Initial account signup** | ❌ No | One-time browser, gives you an API token |

**The only manual part:** signing up once for each service and copying an API token. After that, everything is automated. The scripts below consume those tokens.

---

## 1. One-Time Token Collection (the only manual step)

Do this once. Each gives you a token the scripts will use.

`[HUMAN]` Collect these tokens into a file called `.deploy.env` (gitignored):

```bash
# Neon — https://console.neon.tech/app/settings/api-keys → "Create API Key"
NEON_API_KEY=

# Upstash — https://console.upstash.com/account/api → "Create API Key"
UPSTASH_EMAIL=
UPSTASH_API_KEY=

# Railway — https://railway.app/account/tokens → "Create Token"
RAILWAY_TOKEN=

# LLM providers
XAI_API_KEY=
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
```

That's the entire manual surface. Five dashboards, five tokens, once. Everything below is automated.

---

## 2. The Master Script

`[CLAUDE]` Create `scripts/deploy/provision.sh` — the one command that does everything:

```bash
#!/usr/bin/env bash
set -euo pipefail

# ── Maya Core — full provisioning ───────────────────────────────
# Usage: ./scripts/deploy/provision.sh
# Requires: .deploy.env with all tokens (see §1)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT_DIR"

# Load tokens
if [[ ! -f .deploy.env ]]; then
  echo "❌ .deploy.env not found. See §1 of the deployment doc."
  exit 1
fi
set -a; source .deploy.env; set +a

echo "════════════════════════════════════════"
echo "   Maya Core — Provisioning"
echo "════════════════════════════════════════"

# Step 1: Neon (Postgres + pgvector)
echo ""
echo "▶ [1/5] Provisioning Neon database..."
python scripts/deploy/provision_neon.py

# Step 2: Upstash (Redis)
echo ""
echo "▶ [2/5] Provisioning Upstash Redis..."
python scripts/deploy/provision_upstash.py

# At this point .deploy.generated.env has DATABASE_URL + REDIS_URL
set -a; source .deploy.generated.env; set +a

# Step 3: Enable pgvector
echo ""
echo "▶ [3/5] Enabling pgvector extension..."
python scripts/deploy/enable_pgvector.py

# Step 4: Railway (app + worker)
echo ""
echo "▶ [4/5] Provisioning Railway services..."
bash scripts/deploy/provision_railway.sh

# Step 5: Smoke test
echo ""
echo "▶ [5/5] Running smoke test..."
python scripts/smoke_test.py

echo ""
echo "════════════════════════════════════════"
echo "   ✅ Provisioning complete"
echo "════════════════════════════════════════"
echo ""
echo "Generated connection strings are in .deploy.generated.env"
echo "Talk to Maya:  railway run maya chat"
```

---

## 3. Neon Provisioning Script

`[CLAUDE]` Create `scripts/deploy/provision_neon.py`:

```python
#!/usr/bin/env python3
"""Provision a Neon project + database via the Neon API.
Idempotent: reuses an existing 'maya-core' project if present.
Writes DATABASE_URL to .deploy.generated.env.
"""
import os
import sys
import httpx

NEON_API = "https://console.neon.tech/api/v2"
PROJECT_NAME = "maya-core"
REGION = "aws-eu-central-1"  # Frankfurt; change if needed


def headers():
    key = os.environ["NEON_API_KEY"]
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def find_existing_project(client) -> str | None:
    resp = client.get(f"{NEON_API}/projects", headers=headers())
    resp.raise_for_status()
    for p in resp.json().get("projects", []):
        if p["name"] == PROJECT_NAME:
            return p["id"]
    return None


def create_project(client) -> str:
    payload = {
        "project": {
            "name": PROJECT_NAME,
            "region_id": REGION,
            "pg_version": 16,
        }
    }
    resp = client.post(f"{NEON_API}/projects", headers=headers(), json=payload)
    resp.raise_for_status()
    return resp.json()["project"]["id"]


def get_pooled_connection_uri(client, project_id: str) -> str:
    """Fetch the pooled connection string (required for Mem0)."""
    resp = client.get(
        f"{NEON_API}/projects/{project_id}/connection_uri",
        headers=headers(),
        params={"pooled": "true", "database_name": "neondb", "role_name": "neondb_owner"},
    )
    resp.raise_for_status()
    return resp.json()["uri"]


def main():
    with httpx.Client(timeout=60) as client:
        project_id = find_existing_project(client)
        if project_id:
            print(f"  ↪ Reusing existing project '{PROJECT_NAME}' ({project_id})")
        else:
            project_id = create_project(client)
            print(f"  ✓ Created project '{PROJECT_NAME}' ({project_id})")

        uri = get_pooled_connection_uri(client, project_id)
        # Ensure pooled host
        if "-pooler" not in uri:
            print("  ⚠ Warning: connection URI is not pooled. Mem0 may hit conn limits.")

        # Append to generated env
        with open(".deploy.generated.env", "a") as f:
            f.write(f"DATABASE_URL={uri}\n")
        print("  ✓ DATABASE_URL written to .deploy.generated.env")


if __name__ == "__main__":
    try:
        main()
    except httpx.HTTPStatusError as e:
        print(f"  ❌ Neon API error: {e.response.status_code} {e.response.text}")
        sys.exit(1)
```

---

## 4. Upstash Provisioning Script

`[CLAUDE]` Create `scripts/deploy/provision_upstash.py`:

```python
#!/usr/bin/env python3
"""Provision an Upstash Redis database via the Upstash REST API.
Idempotent: reuses an existing 'maya-redis' database if present.
Writes REDIS_URL to .deploy.generated.env.
"""
import os
import sys
import base64
import httpx

UPSTASH_API = "https://api.upstash.com/v2/redis"
DB_NAME = "maya-redis"
REGION = "eu-west-1"


def auth():
    email = os.environ["UPSTASH_EMAIL"]
    key = os.environ["UPSTASH_API_KEY"]
    token = base64.b64encode(f"{email}:{key}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def find_existing(client) -> dict | None:
    resp = client.get(f"{UPSTASH_API}/databases", headers=auth())
    resp.raise_for_status()
    for db in resp.json():
        if db["database_name"] == DB_NAME:
            return db
    return None


def create_db(client) -> dict:
    payload = {
        "name": DB_NAME,
        "region": REGION,
        "tls": True,
    }
    resp = client.post(f"{UPSTASH_API}/database", headers=auth(), json=payload)
    resp.raise_for_status()
    return resp.json()


def get_redis_url(client, db_id: str) -> str:
    """Fetch full DB details including the rediss:// endpoint."""
    resp = client.get(f"{UPSTASH_API}/database/{db_id}", headers=auth())
    resp.raise_for_status()
    db = resp.json()
    # Build rediss:// URL
    endpoint = db["endpoint"]
    port = db["port"]
    password = db["password"]
    return f"rediss://default:{password}@{endpoint}:{port}"


def main():
    with httpx.Client(timeout=60) as client:
        db = find_existing(client)
        if db:
            print(f"  ↪ Reusing existing Redis '{DB_NAME}'")
            db_id = db["database_id"]
        else:
            db = create_db(client)
            db_id = db["database_id"]
            print(f"  ✓ Created Redis '{DB_NAME}'")

        url = get_redis_url(client, db_id)
        with open(".deploy.generated.env", "a") as f:
            f.write(f"REDIS_URL={url}\n")
        print("  ✓ REDIS_URL written to .deploy.generated.env")


if __name__ == "__main__":
    try:
        main()
    except httpx.HTTPStatusError as e:
        print(f"  ❌ Upstash API error: {e.response.status_code} {e.response.text}")
        sys.exit(1)
```

---

## 5. Enable pgvector Script

`[CLAUDE]` Create `scripts/deploy/enable_pgvector.py`:

```python
#!/usr/bin/env python3
"""Enable the pgvector extension on the provisioned Neon database."""
import os
import sys
import asyncio
import asyncpg


async def main():
    raw_url = os.environ["DATABASE_URL"]
    # asyncpg wants a clean URL without sslmode param
    url = raw_url.replace("?sslmode=require", "").replace("&sslmode=require", "")
    conn = await asyncpg.connect(url, ssl=True)
    try:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        row = await conn.fetchrow(
            "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
        )
        assert row is not None, "pgvector failed to install"
        print("  ✓ pgvector extension enabled")
    finally:
        await conn.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"  ❌ pgvector setup failed: {e}")
        sys.exit(1)
```

---

## 6. Railway Provisioning Script

`[CLAUDE]` Create `scripts/deploy/provision_railway.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

# ── Railway provisioning via CLI ────────────────────────────────
# Requires: RAILWAY_TOKEN env var, and .deploy.generated.env with
# DATABASE_URL + REDIS_URL already populated.

# Install Railway CLI if missing
if ! command -v railway &>/dev/null; then
  echo "  ↪ Installing Railway CLI..."
  npm install -g @railway/cli
fi

# Authenticate non-interactively
export RAILWAY_TOKEN="${RAILWAY_TOKEN}"

# Create project if it doesn't exist (idempotent-ish)
PROJECT_NAME="maya-core"
if ! railway status &>/dev/null; then
  echo "  ↪ Creating Railway project '$PROJECT_NAME'..."
  railway init --name "$PROJECT_NAME"
else
  echo "  ↪ Railway project already linked"
fi

# Load generated + token env
set -a
source .deploy.generated.env
source .deploy.env
set +a

# Push all env vars to Railway
echo "  ↪ Setting environment variables..."
railway variables \
  --set "DATABASE_URL=$DATABASE_URL" \
  --set "REDIS_URL=$REDIS_URL" \
  --set "XAI_API_KEY=$XAI_API_KEY" \
  --set "OPENAI_API_KEY=$OPENAI_API_KEY" \
  --set "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-}" \
  --set "ENVIRONMENT=staging" \
  --set "LITELLM_LOG=ERROR" \
  --set "TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN:-}" \
  --set "TELEGRAM_WEBHOOK_SECRET=${TELEGRAM_WEBHOOK_SECRET:-}" \
  --set "PUBLIC_BASE_URL=${PUBLIC_BASE_URL:-}"

# Telegram (optional): create a bot via @BotFather for TELEGRAM_BOT_TOKEN,
# pick any random TELEGRAM_WEBHOOK_SECRET, and set PUBLIC_BASE_URL to the
# Railway public domain (https://...). The app registers the webhook at
# startup; verify with: curl https://api.telegram.org/bot<token>/getWebhookInfo

# Deploy
echo "  ↪ Deploying..."
railway up --detach

echo "  ✓ Railway deployment triggered"
```

---

## 7. Application Config Files

These are the same runtime files as before — Claude Code creates them once.

### 7.1 `maya/config.py` `[CLAUDE]`

```python
import os
from functools import cached_property
from urllib.parse import urlparse


class Settings:
    def __init__(self):
        self.environment = os.getenv("ENVIRONMENT", "local")
        self.xai_api_key = os.getenv("XAI_API_KEY")
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        self.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
        self._raw_database_url = os.getenv("DATABASE_URL", "")
        self.redis_url = os.getenv("REDIS_URL", "")

    @cached_property
    def database_url_async(self) -> str:
        url = self._raw_database_url
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url.replace("?sslmode=require", "").replace("&sslmode=require", "")

    @cached_property
    def database_url_sync(self) -> str:
        return self._raw_database_url

    @cached_property
    def pg_connection_parts(self) -> dict:
        parsed = urlparse(self._raw_database_url)
        return {
            "host": parsed.hostname,
            "port": parsed.port or 5432,
            "user": parsed.username,
            "password": parsed.password,
            "dbname": parsed.path.lstrip("/").split("?")[0],
        }


settings = Settings()
```

### 7.2 `maya/db/session.py` `[CLAUDE]`

```python
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from maya.config import settings

engine = create_async_engine(
    settings.database_url_async,
    connect_args={"ssl": True},
    pool_size=5,
    max_overflow=2,
    pool_pre_ping=True,
    pool_recycle=300,
)

AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
```

### 7.3 `maya/workers/celery_app.py` `[CLAUDE]`

```python
import ssl
from celery import Celery
from maya.config import settings

celery_app = Celery("maya")
ssl_options = {"ssl_cert_reqs": ssl.CERT_NONE}
is_tls = settings.redis_url.startswith("rediss://")

celery_app.conf.update(
    broker_url=settings.redis_url,
    result_backend=settings.redis_url,
    broker_use_ssl=ssl_options if is_tls else None,
    redis_backend_use_ssl=ssl_options if is_tls else None,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    broker_pool_limit=3,
    worker_prefetch_multiplier=1,
)

celery_app.conf.beat_schedule = {}
```

### 7.4 `maya/memory/config.py` `[CLAUDE]`

```python
from maya.config import settings


def build_mem0_config() -> dict:
    parts = settings.pg_connection_parts
    return {
        "vector_store": {
            "provider": "pgvector",
            "config": {
                "collection_name": "maya_memories",
                "embedding_model_dims": 1536,
                "host": parts["host"],
                "port": parts["port"],
                "user": parts["user"],
                "password": parts["password"],
                "dbname": parts["dbname"],
            },
        },
        "llm": {"provider": "openai", "config": {"model": "gpt-4o-mini", "temperature": 0.1}},
        "embedder": {"provider": "openai", "config": {"model": "text-embedding-3-small"}},
        "version": "v1.1",
    }
```

### 7.5 `nixpacks.toml` `[CLAUDE]`

```toml
[phases.setup]
nixPkgs = ["python311", "postgresql"]

[phases.install]
cmds = ["pip install -r requirements.txt"]

[phases.build]
cmds = ["alembic upgrade head"]

[start]
cmd = "celery -A maya.workers.celery_app worker --loglevel=info --concurrency=2"
```

### 7.6 `Procfile` `[CLAUDE]`

```
web: tail -f /dev/null
worker: celery -A maya.workers.celery_app worker --loglevel=info --concurrency=2
beat: celery -A maya.workers.celery_app beat --loglevel=info
```

(Swap the `web` line for `uvicorn maya.api.main:app --host 0.0.0.0 --port $PORT` when the HTTP layer lands.)

### 7.7 `requirements.txt` `[CLAUDE]`

```
sqlalchemy[asyncio]>=2.0,<2.1
asyncpg>=0.29
alembic>=1.13
pydantic>=2,<3
litellm>=1.40
mem0ai>=0.1.0
celery>=5.3
redis>=5.0
typer>=0.12
structlog>=24.1
python-dotenv>=1.0
tiktoken>=0.7
httpx>=0.27
```

### 7.8 `.gitignore` additions `[CLAUDE]`

```
.deploy.env
.deploy.generated.env
.env
```

---

## 8. Smoke Test

`[CLAUDE]` Create `scripts/smoke_test.py`:

```python
"""Verify all external services are reachable. Exit non-zero on any failure."""
import asyncio
import sys
from maya.config import settings


async def check_database():
    from sqlalchemy import text
    from maya.db.session import engine
    async with engine.connect() as conn:
        assert (await conn.execute(text("SELECT 1"))).scalar() == 1
        ext = await conn.execute(text("SELECT 1 FROM pg_extension WHERE extname='vector'"))
        assert ext.scalar() == 1, "pgvector not installed"
    print("✓ Database (Neon) + pgvector OK")


async def check_redis():
    import redis.asyncio as redis
    r = redis.from_url(settings.redis_url)
    await r.ping()
    await r.aclose()
    print("✓ Redis (Upstash) OK")


def check_llm():
    import litellm
    resp = litellm.completion(
        model="xai/grok-3",
        messages=[{"role": "user", "content": "Say ok"}],
        max_tokens=5,
    )
    assert resp.choices[0].message.content
    print("✓ Grok (xAI) OK")


def check_embeddings():
    import litellm
    resp = litellm.embedding(model="text-embedding-3-small", input=["test"])
    assert len(resp.data[0]["embedding"]) == 1536
    print("✓ OpenAI embeddings OK")


def check_mem0():
    from mem0 import Memory
    from maya.memory.config import build_mem0_config
    Memory.from_config(build_mem0_config())
    print("✓ Mem0 initialized OK")


async def main():
    try:
        await check_database()
        await check_redis()
        check_llm()
        check_embeddings()
        check_mem0()
        print("\n🎉 All systems go.")
    except Exception as e:
        print(f"\n❌ Smoke test failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 9. Makefile Targets

`[CLAUDE]` Add to `Makefile`:

```makefile
.PHONY: deploy.provision deploy.smoke deploy.redeploy deploy.teardown deploy.logs

# Full provisioning from scratch
deploy.provision:
	bash scripts/deploy/provision.sh

# Just run the smoke test (against current env)
deploy.smoke:
	python scripts/smoke_test.py

# Redeploy code without re-provisioning infra
deploy.redeploy:
	railway up --detach

# Tail Railway logs
deploy.logs:
	railway logs

# Tear down everything (careful!)
deploy.teardown:
	python scripts/deploy/teardown.py
```

---

## 10. Teardown Script (Cleanup)

`[CLAUDE]` Create `scripts/deploy/teardown.py`:

```python
#!/usr/bin/env python3
"""Delete all provisioned resources. Use with caution.
Prompts for confirmation before deleting.
"""
import os
import sys
import base64
import httpx


def confirm():
    ans = input("⚠ This deletes Neon + Upstash + Railway resources. Type 'DELETE' to confirm: ")
    if ans != "DELETE":
        print("Aborted.")
        sys.exit(0)


def teardown_neon(client):
    key = os.environ["NEON_API_KEY"]
    h = {"Authorization": f"Bearer {key}"}
    resp = client.get("https://console.neon.tech/api/v2/projects", headers=h)
    for p in resp.json().get("projects", []):
        if p["name"] == "maya-core":
            client.delete(f"https://console.neon.tech/api/v2/projects/{p['id']}", headers=h)
            print(f"  ✓ Deleted Neon project {p['id']}")


def teardown_upstash(client):
    email = os.environ["UPSTASH_EMAIL"]
    key = os.environ["UPSTASH_API_KEY"]
    token = base64.b64encode(f"{email}:{key}".encode()).decode()
    h = {"Authorization": f"Basic {token}"}
    resp = client.get("https://api.upstash.com/v2/redis/databases", headers=h)
    for db in resp.json():
        if db["database_name"] == "maya-redis":
            client.delete(f"https://api.upstash.com/v2/redis/database/{db['database_id']}", headers=h)
            print(f"  ✓ Deleted Upstash DB {db['database_id']}")


def main():
    # Load .deploy.env
    from dotenv import load_dotenv
    load_dotenv(".deploy.env")
    confirm()
    with httpx.Client(timeout=60) as client:
        teardown_neon(client)
        teardown_upstash(client)
    print("\n  ℹ Railway: run 'railway down' manually to remove the project.")
    print("  ✓ Teardown complete.")


if __name__ == "__main__":
    main()
```

---

## 11. The Entire Flow, Start to Finish

```bash
# ── One-time manual step ────────────────────────────
# 1. Sign up for Neon, Upstash, Railway (browser)
# 2. Create an API token in each
# 3. Paste tokens + LLM keys into .deploy.env

# ── Everything else is one command ──────────────────
make deploy.provision

# This single command:
#   → creates Neon project + database
#   → enables pgvector
#   → creates Upstash Redis
#   → creates Railway project
#   → sets all env vars
#   → deploys
#   → runs migrations (via build hook)
#   → runs smoke test
#
# Total time: ~3-5 minutes, mostly waiting on Railway build.

# ── Use it ──────────────────────────────────────────
railway run maya chat
railway run maya seed --user-name "Test"
make deploy.logs

# ── Iterate (redeploy code only) ────────────────────
git push          # if Railway is connected to GitHub, auto-deploys
# OR
make deploy.redeploy

# ── Clean up ────────────────────────────────────────
make deploy.teardown
```

---

## 12. Dependency: `httpx` and CLIs

The provisioning scripts need:
- **Python:** `httpx`, `asyncpg`, `python-dotenv` (already in requirements.txt)
- **System:** Node.js + npm (for Railway CLI), installed by `provision_railway.sh` if missing

`[CLAUDE]` If Node isn't available in the environment, add to the provision script a check:

```bash
if ! command -v npm &>/dev/null; then
  echo "❌ npm required for Railway CLI. Install Node.js first."
  exit 1
fi
```

---

## 13. What's Still Manual (and Why)

Being honest about the irreducible manual surface:

| Manual step | Why it can't be scripted |
|---|---|
| Initial account signup (×3) | Requires human identity / email verification |
| Creating the first API token | Security: tokens are shown once, in-browser |
| Pasting tokens into `.deploy.env` | You hold the secrets, not the script |

**Everything after `.deploy.env` is populated is fully automated.** That's the maximum achievable — cloud providers deliberately gate account creation and first-token issuance behind a human.

---

## 14. API Endpoint Reference (for script maintenance)

If a provider changes their API, here's what the scripts depend on:

| Provider | API base | Auth method | Docs |
|---|---|---|---|
| Neon | `console.neon.tech/api/v2` | Bearer token | `neon.tech/docs/reference/api-reference` |
| Upstash | `api.upstash.com/v2` | Basic (email:key) | `upstash.com/docs/redis/features/restapi` |
| Railway | CLI (`@railway/cli`) | `RAILWAY_TOKEN` env | `docs.railway.app/reference/cli-api` |

---

## Summary for Claude Code

**Create these files:**
1. `scripts/deploy/provision.sh` — master orchestrator (§2)
2. `scripts/deploy/provision_neon.py` (§3)
3. `scripts/deploy/provision_upstash.py` (§4)
4. `scripts/deploy/enable_pgvector.py` (§5)
5. `scripts/deploy/provision_railway.sh` (§6)
6. `scripts/deploy/teardown.py` (§10)
7. `scripts/smoke_test.py` (§8)
8. All runtime config files (§7)
9. Makefile targets (§9)
10. `.gitignore` entries (§7.8)

**Make all `.sh` and `.py` scripts executable** (`chmod +x`).

**The human does exactly one thing:** populate `.deploy.env` with tokens (§1).

**Then one command provisions everything:** `make deploy.provision`.

**Definition of done:** `make deploy.provision` completes with the smoke test printing all green, with no manual steps between populating `.deploy.env` and a working deployment.
