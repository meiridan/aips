"""Single-companion resolution.

The app is single-user by product decision: the web UI and the Telegram bot
both talk to ONE shared Maya. This resolves (and lazily creates) that one
(user, companion) pair so every channel converges on the same companion +
memory. Ordering by created_at makes the choice deterministic across channels.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from maya.companions.genesis import run_genesis
from maya.db.models import Companion, User
from maya.db.session import get_sessionmaker


async def resolve_singleton(
    sessionmaker: Any = None,
) -> tuple[uuid.UUID, uuid.UUID, bool, str | None]:
    """Return (user_id, companion_id, created, first_message).

    Picks the oldest companion. If none exists yet, creates a user + companion
    and runs genesis; `created` is True and `first_message` is Maya's opener.
    """
    sm = sessionmaker or get_sessionmaker()
    async with sm() as session:
        comp = (
            await session.execute(
                select(Companion).order_by(Companion.created_at.asc()).limit(1)
            )
        ).scalar_one_or_none()
        if comp is not None:
            return comp.user_id, comp.id, False, None

        user = User(name="Maya User")
        session.add(user)
        await session.flush()
        comp = Companion(user_id=user.id, name="Maya", template_id="flirt")
        session.add(comp)
        await session.commit()
        user_id, companion_id = user.id, comp.id

    result = await run_genesis(companion_id, sessionmaker=sm)
    return user_id, companion_id, True, result.first_message
