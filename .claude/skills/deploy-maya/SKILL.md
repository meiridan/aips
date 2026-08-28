---
name: deploy-maya
description: Deploy, redeploy, or troubleshoot Maya Core's Railway/Neon/Upstash production deployment. Use when asked to deploy, redeploy, check deploy logs, run a smoke test against prod, or tear down the deployment.
disable-model-invocation: true
---

Maya Core runs on Railway (service `maya-core`, region sfo), Neon Postgres+pgvector (project `maya-core`), and Upstash Redis (`maya-redis`). One uvicorn process (`maya.web:app`) serves both the web UI/WebSocket and the Telegram webhook.

Live at: https://maya-core-production-3608.up.railway.app

## Commands

- `make deploy.provision` — full initial provisioning (`scripts/deploy/provision.sh`)
- `make deploy.redeploy` — redeploy current code (`railway up --service maya-core --detach`)
- `make deploy.smoke` — run `scripts/smoke_test.py` against prod with the DATABASE_URL converted for asyncpg
- `make deploy.logs` — tail Railway logs
- `make deploy.teardown` — tear down the deployment (`scripts/deploy/teardown.py`) — destructive, confirm with the user first

## Gotchas (read before debugging deploy failures)

1. **Zscaler MITM proxy** on this dev machine re-signs HTTPS with a private root CA. Python scripts rely on `truststore.inject_into_ssl()`; the Railway CLI needs `SSL_CERT_FILE` pointing at the exported Zscaler root CA (`.zscaler-root-ca.pem`, auto-exported by `provision.sh`). Plain `certifi` fails with TLS errors here — that's expected, not a real cert problem.
2. **Railway auth**: the account token is `RAILWAY_API_TOKEN`, not `RAILWAY_TOKEN` — `RAILWAY_TOKEN` is for project-scoped tokens. It lives in `.deploy.env` as `RAILWAY_TOKEN`; the deploy scripts remap it. If auth fails, check the remap, not the token value.
3. **No build hook**: Railway builds with railpack (auto-detects uv + Procfile) and runs no build-time migration hook. Migrations are applied **locally** against Neon during `provision.sh`, before/after deploy — not automatically on the server.
4. **DATABASE_URL format**: must be `postgresql+asyncpg://...?ssl=require`. Neon's raw connection string needs conversion via `scripts/deploy/asyncpg_url.py` — don't paste Neon's URL directly into env vars.
5. **Upload size**: `railway up` uploads the working tree (not git), so `.railwayignore` (excludes the ~377MB `.venv`) is what keeps upload size sane — check it if a deploy suddenly gets slow or huge.
6. **Telegram webhook** auto-registers at app startup when `TELEGRAM_BOT_TOKEN` + `PUBLIC_BASE_URL` are set. Verify registration with `curl https://api.telegram.org/bot<token>/getWebhookInfo`.

After any redeploy, run `make deploy.smoke` before telling the user it's done.
