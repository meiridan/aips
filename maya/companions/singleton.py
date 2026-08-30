"""Companion resolution, per account.

This module used to resolve ONE shared Maya for the whole app (the oldest
companion row), because Maya was single-user by product decision. Accounts
changed that: the web channel resolves the signed-in user's companion, and
Telegram resolves the companion belonging to the chat it is talking to.

The two channels differ in one way that matters. The web UI has a creation
wizard, so a new account's companion is an empty row until the wizard submits a
spec and pays for genesis. Telegram has no wizard, so a first-time chat has to
bring a default companion to life immediately or it would answer with nothing.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from maya import runtime_cache
from maya.companions.genesis import run_genesis
from maya.db.models import Companion, User
from maya.db.session import get_sessionmaker


async def resolve_for_user(
    sessionmaker: Any = None,
    *,
    user_id: uuid.UUID,
) -> uuid.UUID:
    """Return the companion id for an account, creating an empty one if needed.

    Never runs genesis: on the web the creation wizard owns that, and paying
    for a default birth here would spend an LLM call and seed an opener in the
    wrong voice before the user has said who she is.

    The (user → companion) mapping is immutable once created, so it is cached.
    """
    cached = runtime_cache.get_companion_for_user(user_id)
    if cached is not None:
        return cached

    sm = sessionmaker or get_sessionmaker()
    async with sm() as session:
        comp = (
            await session.execute(
                select(Companion)
                .where(Companion.user_id == user_id)
                .order_by(Companion.created_at.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if comp is None:
            comp = Companion(user_id=user_id, name="Maya", template_id="flirt")
            session.add(comp)
            await session.commit()
        companion_id = comp.id

    runtime_cache.set_companion_for_user(user_id, companion_id)
    return companion_id


async def resolve_by_telegram_chat(
    sessionmaker: Any = None,
    *,
    chat_id: int,
) -> tuple[uuid.UUID, uuid.UUID, bool, str | None]:
    """Return (user_id, companion_id, created, first_message) for a Telegram chat.

    `users.telegram_chat_id` is the account key for this channel. A chat that
    has never been seen gets its own account and companion, and — because there
    is no wizard on Telegram — genesis runs so she has a persona and an opener.
    """
    sm = sessionmaker or get_sessionmaker()

    cached = runtime_cache.get_user_for_telegram_chat(chat_id)
    if cached is not None:
        return cached, await resolve_for_user(sm, user_id=cached), False, None

    async with sm() as session:
        user = (
            await session.execute(select(User).where(User.telegram_chat_id == chat_id))
        ).scalar_one_or_none()
        if user is not None:
            user_id = user.id
        else:
            user = User(name="Maya User", telegram_chat_id=chat_id)
            session.add(user)
            await session.commit()
            user_id = user.id

    runtime_cache.set_user_for_telegram_chat(chat_id, user_id)

    known = await _has_companion(sm, user_id)
    companion_id = await resolve_for_user(sm, user_id=user_id)
    if known:
        return user_id, companion_id, False, None

    result = await run_genesis(companion_id, sessionmaker=sm)
    return user_id, companion_id, True, result.first_message


async def _has_companion(sessionmaker: Any, user_id: uuid.UUID) -> bool:
    async with sessionmaker() as session:
        return (
            await session.execute(select(Companion.id).where(Companion.user_id == user_id).limit(1))
        ).scalar_one_or_none() is not None
