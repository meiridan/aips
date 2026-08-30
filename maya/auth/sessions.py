"""Opaque server-side sessions.

The cookie carries a random token; the database stores only its SHA-256. That
means a leaked `sessions` table hands over nothing usable, and — unlike a
signed/JWT cookie — a password reset can revoke every outstanding session by
touching one table.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update

from maya.config import get_settings
from maya.db.models import UserSession

COOKIE_NAME = "maya_session"

# How stale `last_seen_at` may get before a read bothers to write. Without this
# every authenticated request would issue an UPDATE just to slide the window.
_RENEW_AFTER = timedelta(hours=1)

_TOKEN_BYTES = 32


def _hash_token(token: str) -> str:
    """SHA-256 hex of the cookie value.

    A plain hash, not a KDF: the token is 256 bits of `secrets` output, so
    there is no low-entropy secret to protect and no reason to pay scrypt's
    92 ms on every request.
    """
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _ttl() -> timedelta:
    return timedelta(days=get_settings().session_ttl_days)


async def issue(
    sessionmaker: Any,
    user_id: uuid.UUID,
    *,
    user_agent: str | None = None,
    ip: str | None = None,
) -> str:
    """Create a session and return the raw token to put in the cookie.

    The raw token is returned exactly once and never stored.
    """
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    async with sessionmaker() as session:
        session.add(
            UserSession(
                user_id=user_id,
                token_hash=_hash_token(token),
                expires_at=datetime.now(UTC) + _ttl(),
                user_agent=(user_agent or None),
                ip=(ip or None),
            )
        )
        await session.commit()
    return token


async def resolve(sessionmaker: Any, token: str | None) -> uuid.UUID | None:
    """Return the owning user id for a live session token, else None.

    Slides the expiry window on use, at most once per `_RENEW_AFTER`.
    """
    if not token:
        return None
    token_hash = _hash_token(token)
    now = datetime.now(UTC)
    async with sessionmaker() as session:
        row = (
            await session.execute(select(UserSession).where(UserSession.token_hash == token_hash))
        ).scalar_one_or_none()
        if row is None or row.revoked_at is not None or row.expires_at <= now:
            return None
        user_id = row.user_id
        if now - row.last_seen_at >= _RENEW_AFTER:
            row.last_seen_at = now
            row.expires_at = now + _ttl()
            await session.commit()
    return user_id


async def revoke(sessionmaker: Any, token: str | None) -> None:
    """Revoke one session (logout). Unknown tokens are a no-op."""
    if not token:
        return
    async with sessionmaker() as session:
        await session.execute(
            update(UserSession)
            .where(UserSession.token_hash == _hash_token(token))
            .where(UserSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        await session.commit()


async def revoke_all(sessionmaker: Any, user_id: uuid.UUID) -> None:
    """Revoke every live session for a user.

    Called after a password reset: whoever prompted the reset must be logged
    out everywhere, including wherever an attacker still holds a cookie.
    """
    async with sessionmaker() as session:
        await session.execute(
            update(UserSession)
            .where(UserSession.user_id == user_id)
            .where(UserSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        await session.commit()


def max_age_seconds() -> int:
    """Cookie lifetime, matched to the row's expiry so the browser and the
    database agree on when a session is over."""
    return int(_ttl().total_seconds())


def cookie_params() -> dict[str, Any]:
    """Keyword arguments for `response.set_cookie` / `delete_cookie`.

    `SameSite=Lax` plus a same-origin SPA is what lets the JSON endpoints skip
    CSRF tokens: a cross-site POST won't carry this cookie. `Secure` is off
    locally only because http://localhost would otherwise drop it.
    """
    settings = get_settings()
    return {
        "httponly": True,
        "samesite": "lax",
        "secure": settings.environment != "local",
        "path": "/",
    }
