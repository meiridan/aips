"""Account lookup and creation on the existing `users` table.

`users` is the account row — there is no separate accounts table. A row may
have a password, a Google subject, both (linked by email), or neither (the
pre-auth rows this app started with).
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from maya.auth.passwords import hash_password, verify_password, waste_time_like_a_verify
from maya.db.models import User

# Deliberately permissive: the only authority on whether an address works is
# whether mail to it arrives. This rejects the obviously-not-an-address, not
# the merely-unusual.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")
MAX_EMAIL_LENGTH = 254


def normalize(email: str) -> str:
    """The form stored in `email_normalized` and used by every lookup."""
    return email.strip().lower()


def email_problem(email: str) -> str | None:
    """Return a UI string key describing why an address is unusable."""
    cleaned = email.strip()
    if not cleaned:
        return "email_required"
    if len(cleaned) > MAX_EMAIL_LENGTH or not _EMAIL_RE.match(cleaned):
        return "email_invalid"
    return None


def _name_from_email(email: str) -> str:
    """`users.name` is NOT NULL and is what the companion calls the user."""
    local = normalize(email).split("@", 1)[0]
    return local.replace(".", " ").replace("_", " ").strip().title() or "You"


async def get_by_email(sessionmaker: Any, email: str) -> User | None:
    async with sessionmaker() as session:
        return (
            await session.execute(select(User).where(User.email_normalized == normalize(email)))
        ).scalar_one_or_none()


async def get_by_google_sub(sessionmaker: Any, google_sub: str) -> User | None:
    async with sessionmaker() as session:
        return (
            await session.execute(select(User).where(User.google_sub == google_sub))
        ).scalar_one_or_none()


async def get(sessionmaker: Any, user_id: uuid.UUID) -> User | None:
    async with sessionmaker() as session:
        return await session.get(User, user_id)


async def create(
    sessionmaker: Any,
    *,
    email: str,
    password: str | None = None,
    google_sub: str | None = None,
    name: str | None = None,
    email_verified: bool = False,
) -> User:
    """Create an account. Does not create a companion — `resolve_for_user`
    does that lazily, so signup stays fast and genesis waits for the wizard."""
    now = datetime.now(UTC)
    async with sessionmaker() as session:
        user = User(
            name=name or _name_from_email(email),
            email=email.strip(),
            email_normalized=normalize(email),
            password_hash=hash_password(password) if password else None,
            google_sub=google_sub,
            email_verified_at=now if email_verified else None,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def link_google(sessionmaker: Any, user_id: uuid.UUID, google_sub: str) -> None:
    """Attach a Google subject to an existing account matched by email."""
    async with sessionmaker() as session:
        user = await session.get(User, user_id)
        if user is not None and user.google_sub is None:
            user.google_sub = google_sub
            # Google vouched for the address, so stop treating it as unverified.
            user.email_verified_at = user.email_verified_at or datetime.now(UTC)
            await session.commit()


async def set_password(sessionmaker: Any, user_id: uuid.UUID, password: str) -> None:
    async with sessionmaker() as session:
        user = await session.get(User, user_id)
        if user is None:
            raise ValueError(f"User {user_id} not found")
        user.password_hash = hash_password(password)
        await session.commit()


async def note_login(sessionmaker: Any, user_id: uuid.UUID) -> None:
    async with sessionmaker() as session:
        user = await session.get(User, user_id)
        if user is not None:
            user.last_login_at = datetime.now(UTC)
            await session.commit()


async def authenticate(sessionmaker: Any, email: str, password: str) -> User | None:
    """Return the user for correct credentials, else None.

    Runs a hash even when the email is unknown so the failure path costs the
    same either way — otherwise response timing tells an attacker which
    addresses have accounts.
    """
    user = await get_by_email(sessionmaker, email)
    if user is None:
        waste_time_like_a_verify()
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user
