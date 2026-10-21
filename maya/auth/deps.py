"""FastAPI dependencies that turn a session cookie into a user."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, Request, WebSocket

from maya.auth import accounts, sessions
from maya.config import get_settings
from maya.db.models import User
from maya.db.session import get_sessionmaker
from maya.logging import get_logger

log = get_logger("maya.auth")

#: The account every request lands on while DEV_AUTOLOGIN is set. A real row in
#: `users`, so it owns a normal companion, messages and memories.
DEV_ACCOUNT_EMAIL = "dev@local.test"

#: The account every request lands on in single-user mode when no row is pinned
#: via MAYA_SINGLE_USER_ID. Created without a password, so it cannot be logged
#: into even after the login flow comes back.
SOLO_ACCOUNT_EMAIL = "solo@maya.local"

#: Resolved id of the single-user account, so the steady state is one primary-key
#: lookup instead of an email lookup per request.
_solo_user_id: uuid.UUID | None = None


def single_user_enabled() -> bool:
    """Whether the login flow is out of the picture entirely.

    One condition, not two: unlike :func:`dev_autologin_enabled` this is *not*
    gated on a local environment, so a deployed instance is open as well.
    """
    return get_settings().single_user


def reset_solo_cache() -> None:
    """Forget the memoized single-user id (tests, and after a DB reset)."""
    global _solo_user_id
    _solo_user_id = None


async def _solo_account() -> User:
    """The one account single-user mode serves, created on first use."""
    global _solo_user_id
    sm = get_sessionmaker()
    pinned = _solo_user_id or _configured_solo_id()
    if pinned is not None:
        user = await accounts.get(sm, pinned)
        if user is not None:
            _solo_user_id = user.id
            return user
        # A stale MAYA_SINGLE_USER_ID would otherwise 500 every request; fall
        # back to the sentinel account instead.
        log.warning("single_user_row_missing", user_id=str(pinned))
        _solo_user_id = None

    user = await accounts.get_by_email(sm, SOLO_ACCOUNT_EMAIL)
    if user is None:
        user = await accounts.create(sm, email=SOLO_ACCOUNT_EMAIL, name="Maya", email_verified=True)
        log.warning("single_user_account_created", email=SOLO_ACCOUNT_EMAIL)
    _solo_user_id = user.id
    return user


def _configured_solo_id() -> uuid.UUID | None:
    raw = get_settings().maya_single_user_id
    if not raw:
        return None
    try:
        return uuid.UUID(raw.strip())
    except ValueError:
        log.warning("single_user_id_invalid", value=raw)
        return None


def dev_autologin_enabled() -> bool:
    """Whether the login screen is bypassed.

    Two conditions, not one: the flag *and* a local environment. A deployed
    instance ignores the flag entirely even if the env var leaks into it.
    """
    settings = get_settings()
    return settings.dev_autologin and settings.environment == "local"


async def _dev_account() -> User:
    """Get-or-create the fixed dev account. Local only — see the caller."""
    sm = get_sessionmaker()
    user = await accounts.get_by_email(sm, DEV_ACCOUNT_EMAIL)
    if user is None:
        user = await accounts.create(sm, email=DEV_ACCOUNT_EMAIL, name="Dev", email_verified=True)
        log.warning("dev_autologin_account_created", email=DEV_ACCOUNT_EMAIL)
    return user


def session_token(request: Request) -> str | None:
    return request.cookies.get(sessions.COOKIE_NAME)


async def optional_user(request: Request) -> User | None:
    """The signed-in user, or None. For routes that serve both."""
    if single_user_enabled():
        return await _solo_account()
    user_id = await sessions.resolve(get_sessionmaker(), session_token(request))
    if user_id is None:
        return await _dev_account() if dev_autologin_enabled() else None
    return await accounts.get(get_sessionmaker(), user_id)


async def current_user(request: Request) -> User:
    """The signed-in user, or 401.

    One detail matters: 401 (not 403) is what the SPA's `json<T>()` helper
    watches for to flip to the logged-out state.
    """
    user = await optional_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="not_authenticated")
    return user


async def user_id_from_websocket(websocket: WebSocket) -> uuid.UUID | None:
    """Resolve the session from the WebSocket handshake's cookies.

    Starlette exposes handshake cookies on the connection, so the browser's
    same-origin cookie authenticates the socket with no token in the URL —
    which would otherwise end up in logs and referrers.
    """
    if single_user_enabled():
        return (await _solo_account()).id
    user_id = await sessions.resolve(
        get_sessionmaker(), websocket.cookies.get(sessions.COOKIE_NAME)
    )
    if user_id is None and dev_autologin_enabled():
        return (await _dev_account()).id
    return user_id
