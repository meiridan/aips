"""Simple web UI for Maya with debug flow visualization."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text

from maya.api.auth import router as auth_router
from maya.api.billing import router as billing_router
from maya.api.google_auth import router as google_router
from maya.auth import google
from maya.auth.deps import current_user, dev_autologin_enabled, user_id_from_websocket
from maya.billing import entitlements
from maya.companions import catalog
from maya.companions.onboarding import AlreadyOnboarded, create_companion, get_state
from maya.companions.persona_spec import PersonaSpec
from maya.companions.settings import set_response_length
from maya.companions.singleton import resolve_for_user
from maya.config import get_settings
from maya.conversation import response_length
from maya.conversation.orchestrator import (
    MEMORY_LIMIT,
    RECENT_LIMIT,
    Orchestrator,
)
from maya.db.models import Companion, Message, User
from maya.db.session import get_engine, get_sessionmaker
from maya.logging import configure_logging, get_logger
from maya.telegram.service import get_telegram_service

log = get_logger("maya.web")

# Full history is only replayed on WS (re)connect; the UI reconnects every 2s on
# drop, so cap the replay. Per-turn context still uses RECENT_LIMIT.
HISTORY_REPLAY_LIMIT = 200

# Application close code for "your session is gone". Codes in 4000-4999 are
# reserved for the application, and the browser can read them.
WS_UNAUTHENTICATED = 4401

# One shared orchestrator for all WebSocket connections. Building it runs Mem0's
# slow sync init (opens its own Neon connection); doing it per-connect blocked
# the event loop on every reconnect. Same rationale as the Telegram channel.
_orchestrator: Orchestrator | None = None


def get_orchestrator() -> Orchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator


# Re-exported so callers/tests can confirm the web path uses the shared
# orchestrator constants instead of hardcoded context limits (regression guard
# for the old 3/10 duplication bug — now structurally impossible after the
# single-orchestrator refactor).
__all__ = ["app", "MEMORY_LIMIT", "RECENT_LIMIT"]


async def _warmup() -> None:
    """Pre-pay first-request costs so the first turn after boot/idle is fast.

    Wakes Neon from scale-to-zero, primes the connection pool and builds the
    shared orchestrator (Mem0 init) off the request path. Best-effort — a
    hiccup here must not block boot.

    Since accounts landed there is no single companion to pre-load: whose
    caches to warm is not known until someone signs in. The pool ping was
    always the part that mattered for the Neon cold start."""
    try:
        engine = get_engine()

        async def _ping() -> None:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))

        # Open a few connections concurrently to prime the pool + wake Neon.
        await asyncio.gather(*[_ping() for _ in range(5)])

        # Build the shared orchestrator (slow Mem0 sync init) off the request path.
        get_orchestrator()
        log.info("warmup_complete")
    except Exception as exc:  # noqa: BLE001 - warmup is best-effort
        log.warning("warmup_failed", error=str(exc))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Register the Telegram webhook on boot when fully configured (no-op locally)."""
    settings = get_settings()
    service = get_telegram_service()
    if service is not None and settings.public_base_url:
        url = f"{settings.public_base_url.rstrip('/')}/telegram/webhook"
        await service.client.set_webhook(url, settings.telegram_webhook_secret)
    await _warmup()
    yield


app = FastAPI(title="Maya Web UI", lifespan=lifespan)

# Auth lives in its own router; the wizard/chat routes below predate it and
# stay here.
app.include_router(auth_router)
app.include_router(google_router)
app.include_router(billing_router)


# Configure logging
configure_logging(get_settings().litellm_log)


# The SPA (Vite build output) and the curated wizard imagery. Both are committed
# to the repo: Railway builds via railpack (uv + Procfile) with no build-time
# hook, so Node never runs on the server — see CLAUDE.md and `make ui`.
STATIC_DIR = Path(__file__).resolve().parent / "static"
MEDIA_DIR = Path(__file__).resolve().parent / "media"

if (STATIC_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")
if MEDIA_DIR.is_dir():
    app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")


UNBUILT_HTML = """<!doctype html>
<html lang="he" dir="rtl"><head><meta charset="utf-8"><title>Maya</title></head>
<body style="font-family:sans-serif;background:#0a0a0f;color:#eee;padding:40px">
<h1>הממשק לא נבנה</h1>
<p>הריצו <code dir="ltr">make ui</code> כדי לבנות את ה-SPA אל <code dir="ltr">maya/static/</code>.</p>
</body></html>"""


@app.get("/")
async def get_index():
    """Serve the SPA shell; it decides wizard-vs-chat from /api/companion."""
    index = STATIC_DIR / "index.html"
    if index.is_file():
        return FileResponse(index, media_type="text/html")
    return HTMLResponse(UNBUILT_HTML, status_code=503)


# ───────────────────────────── creation wizard API ────────────────────────


@app.get("/api/catalog")
async def get_catalog() -> dict:
    """Every wizard option with its Hebrew label and tile — the SPA hardcodes none.

    Also carries which sign-in methods are actually available, so the login
    screen can hide a "Continue with Google" button that would only lead to a
    503. Public, because the login screen renders before anyone is signed in.
    """
    return {
        **catalog.as_dict(),
        "auth": {"google": google.is_configured(), "dev_login": dev_autologin_enabled()},
    }


@app.get("/api/companion")
async def get_companion(user: User = Depends(current_user)) -> dict:
    """Onboarding state + saved spec. `onboarded` gates wizard vs chat."""
    sm = get_sessionmaker()
    cid = await resolve_for_user(sm, user_id=user.id)
    return await get_state(sm, cid)


class CreateCompanionRequest(PersonaSpec):
    """A wizard submission: the spec plus an explicit re-creation flag."""

    reset: bool = False


@app.post("/api/companion")
async def post_companion(
    payload: CreateCompanionRequest, user: User = Depends(current_user)
) -> dict:
    """Apply the wizard spec and run genesis. Slow by design (one LLM call)."""
    spec = PersonaSpec.model_validate(payload.model_dump(exclude={"reset"}))
    sm = get_sessionmaker()
    cid = await resolve_for_user(sm, user_id=user.id)
    try:
        first_message = await create_companion(sm, cid, spec, reset=payload.reset)
    except AlreadyOnboarded:
        raise HTTPException(
            status_code=409, detail="companion already created; pass reset=true"
        ) from None
    return {"ok": True, "first_message": first_message}


@app.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict:
    """Inbound Telegram updates. Always answers 200 fast; rejects forged calls."""
    settings = get_settings()
    service = get_telegram_service()
    if service is None:
        raise HTTPException(status_code=404, detail="Telegram not configured")
    if x_telegram_bot_api_secret_token != settings.telegram_webhook_secret:
        raise HTTPException(status_code=403, detail="bad secret token")

    update = await request.json()
    # Run inline: Telegram tolerates webhook latency and the typing indicator
    # covers the wait. If a turn ever risks the ~60s webhook timeout, switch to
    # asyncio.create_task(service.handle_update(update)) and return immediately.
    await service.handle_update(update)
    return {"ok": True}


@app.get("/companion/response_length")
async def get_response_length(user: User = Depends(current_user)) -> dict:
    """Current reply-length level (1=short, 2=medium, 3=long) of this companion."""
    sm = get_sessionmaker()
    cid = await resolve_for_user(sm, user_id=user.id)
    async with sm() as session:
        comp = await session.get(Companion, cid)
        level = response_length.normalize(getattr(comp, "response_length", response_length.DEFAULT))
    return {"level": level}


@app.post("/companion/response_length")
async def post_response_length(request: Request, user: User = Depends(current_user)) -> dict:
    """Set this companion's reply-length level (1|2|3)."""
    body = await request.json()
    level = response_length.parse(str(body.get("level")))
    if level is None:
        raise HTTPException(status_code=422, detail="level must be 1, 2, or 3")
    sm = get_sessionmaker()
    cid = await resolve_for_user(sm, user_id=user.id)
    stored = await set_response_length(sm, cid, level)
    return {"ok": True, "level": stored}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time chat and debug info."""
    # Accept BEFORE rejecting an unauthenticated socket: a refused handshake
    # reaches the browser as a generic connection failure with no readable
    # close code, and the SPA needs 4401 to tell "session expired" (stop
    # retrying, show the login screen) from "server restarting" (keep retrying).
    await websocket.accept()

    user_id = await user_id_from_websocket(websocket)
    if user_id is None:
        await websocket.close(code=WS_UNAUTHENTICATED)
        return

    sm = get_sessionmaker()
    companion_id = await resolve_for_user(sm, user_id=user_id)

    await send_debug(
        websocket,
        "system",
        "Session initialized",
        {"user_id": str(user_id), "companion_id": str(companion_id)},
    )

    # Replay recent message history in chronological order (capped — see
    # HISTORY_REPLAY_LIMIT). Fetch newest-first with a LIMIT, then reverse.
    async with sm() as session:
        stmt = (
            select(Message)
            .where(Message.companion_id == companion_id)
            .order_by(Message.created_at.desc())
            .limit(HISTORY_REPLAY_LIMIT)
        )
        history = list((await session.scalars(stmt)).all())
        history.reverse()

    for msg in history:
        await websocket.send_json(
            {
                "type": "message",
                "role": msg.role,
                "content": msg.content,
            }
        )

    await websocket.send_json({"type": "history_end"})

    orch = get_orchestrator()

    async def on_step(category: str, label: str, data: dict) -> None:
        # The orchestrator emits its own "received" step; skip the echo here.
        await send_debug(websocket, category, label, data)

    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()
            message_data = json.loads(data)
            content = message_data.get("content", "").strip()

            if not content:
                continue

            # The entitlement gate. Server-side and before any work: hiding
            # the compose box would be a hint, not a limit.
            if await entitlements.quota_exceeded(sm, user_id):
                await websocket.send_json({"type": "quota_exceeded"})
                continue

            # Echo user message
            await websocket.send_json({"type": "message", "role": "user", "content": content})

            # Stream the assistant reply token-by-token (perceived latency win).
            # message_end is sent the moment the reply finishes streaming —
            # BEFORE post-processing — so the input re-enables immediately and
            # bookkeeping runs in the background of the turn.
            ended = {"sent": False}

            async def send_end(_ended=ended) -> None:
                if not _ended["sent"]:
                    _ended["sent"] = True
                    await websocket.send_json({"type": "message_end"})

            try:
                await websocket.send_json({"type": "message_start", "role": "assistant"})
                async for piece in orch.stream_message(
                    user_id,
                    companion_id,
                    content,
                    on_step=on_step,
                    on_reply_done=lambda _r: send_end(),
                ):
                    await websocket.send_json({"type": "message_chunk", "content": piece})
                await send_end()
            except Exception as e:
                await send_debug(websocket, "error", f"❌ {type(e).__name__}: {e}", {})
                await send_end()
                continue

    except WebSocketDisconnect:
        await send_debug(websocket, "system", "Client disconnected", {})


async def send_debug(websocket: WebSocket, category: str, label: str, data: dict):
    """Send debug info to client."""
    try:
        await websocket.send_json(
            {"type": "debug", "category": category, "label": label, "data": data}
        )
    except Exception:
        pass  # Client might have disconnected


# ───────────────────────── SPA client routes ──────────────────────────────
# Registered LAST so it cannot shadow anything above: FastAPI matches routes in
# definition order, and the /assets and /media mounts are declared near the top.
#
# The SPA now has real URLs (/login, /reset-password?token=..., /subscription),
# and a password-reset link is opened cold from an email client — so a deep GET
# has to return the app shell rather than a 404.

# Paths owned by the server. A miss under one of these is a genuine 404, not a
# client route; answering with HTML would turn a typo'd endpoint into a
# confusing 200 that breaks the SPA's `json<T>()` error handling.
_SERVER_PREFIXES = (
    "api/",
    "auth/",
    "billing/",
    "companion/",
    "telegram/",
    "assets/",
    "media/",
    "ws",
)


@app.get("/{full_path:path}")
async def spa_catch_all(full_path: str):
    """Serve the SPA shell for client-side routes."""
    if full_path.startswith(_SERVER_PREFIXES):
        raise HTTPException(status_code=404, detail="not_found")
    return await get_index()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
