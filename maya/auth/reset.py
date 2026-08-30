"""Password-reset tokens.

Same shape as sessions: a random token goes out, only its SHA-256 is stored.
Additionally short-lived and single-use, because a reset link sits in an inbox
indefinitely and is the one credential that can take over an account outright.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update

from maya.auth import accounts, sessions
from maya.config import get_settings
from maya.db.models import PasswordResetToken

TOKEN_TTL = timedelta(hours=1)
_TOKEN_BYTES = 32


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def reset_url(token: str) -> str:
    """The link that goes in the email."""
    settings = get_settings()
    base = settings.password_reset_url_base or (
        f"{settings.public_base_url.rstrip('/')}/reset-password"
        if settings.public_base_url
        else "http://localhost:8000/reset-password"
    )
    return f"{base}?token={token}"


async def issue(sessionmaker: Any, user_id: uuid.UUID) -> str:
    """Create a reset token and return the raw value for the email.

    Any earlier outstanding token for this user is invalidated: asking for a
    second link should retire the first, so a forwarded or intercepted older
    email stops working.
    """
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    now = datetime.now(UTC)
    async with sessionmaker() as session:
        await session.execute(
            update(PasswordResetToken)
            .where(PasswordResetToken.user_id == user_id)
            .where(PasswordResetToken.used_at.is_(None))
            .values(used_at=now)
        )
        session.add(
            PasswordResetToken(
                user_id=user_id,
                token_hash=_hash_token(token),
                expires_at=now + TOKEN_TTL,
            )
        )
        await session.commit()
    return token


async def consume(sessionmaker: Any, token: str, new_password: str) -> bool:
    """Apply a reset. Returns False for a missing, expired or already-used token.

    On success every session for that account is revoked. Whoever asked for the
    reset has to sign in again, and — the point — so does anyone else holding a
    cookie for the account.
    """
    if not token:
        return False
    now = datetime.now(UTC)
    async with sessionmaker() as session:
        row = (
            await session.execute(
                select(PasswordResetToken).where(
                    PasswordResetToken.token_hash == _hash_token(token)
                )
            )
        ).scalar_one_or_none()
        if row is None or row.used_at is not None or row.expires_at <= now:
            return False
        user_id = row.user_id
        row.used_at = now
        await session.commit()

    await accounts.set_password(sessionmaker, user_id, new_password)
    await sessions.revoke_all(sessionmaker, user_id)
    return True
