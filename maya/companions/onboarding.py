"""Creation-wizard write path.

Web routes stay thin: this module owns validating a spec onto the companion row,
wiping prior state on an explicit reset, running genesis and invalidating the
runtime cache. The app is still single-companion (see
:mod:`maya.companions.singleton`) — the wizard configures *the* Maya rather than
creating a second one.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete

from maya import runtime_cache
from maya.companions.avatars import resolve_avatar
from maya.companions.genesis import run_genesis
from maya.companions.persona_spec import PersonaSpec
from maya.conversation import response_length
from maya.conversation.rooms import wipe_group_rooms
from maya.db.models import (
    Companion,
    CompanionCommitment,
    EmotionalState,
    Memory,
    Message,
    RelationshipEvent,
    RelationshipState,
)
from maya.logging import get_logger

log = get_logger("maya.onboarding")

DEFAULT_LOCALE = "he"


class AlreadyOnboarded(RuntimeError):
    """Raised when a spec is submitted for a companion that already went live."""


async def get_state(sessionmaker: Any, companion_id: uuid.UUID) -> dict[str, Any]:
    """What the SPA needs to decide wizard-vs-chat, and to prefill the wizard."""
    async with sessionmaker() as session:
        comp = await session.get(Companion, companion_id)
        if comp is None:
            raise ValueError(f"Companion {companion_id} not found")
        return {
            "onboarded": comp.onboarded_at is not None,
            "name": comp.name,
            "avatar_path": comp.avatar_path,
            "locale": comp.locale,
            "spec": (comp.persona_spec or None) or None,
            "response_length": response_length.normalize(comp.response_length),
        }


async def _wipe_history(session: Any, companion_id: uuid.UUID) -> None:
    """Drop every trace of the previous life so a reset is a real restart.

    Order matters: the tables that point at `messages` go first, so the wipe
    also works against a database that predates 0010 (which made that reference
    ON DELETE SET NULL).

    Every group room she is in is cleared too: the partner answering lines
    nobody remembers saying is worse than starting that room over.
    """
    await wipe_group_rooms(session, companion_id)
    for model in (
        CompanionCommitment,
        Memory,
        Message,
        RelationshipEvent,
        RelationshipState,
        EmotionalState,
    ):
        await session.execute(delete(model).where(model.companion_id == companion_id))


async def create_companion(
    sessionmaker: Any,
    companion_id: uuid.UUID,
    spec: PersonaSpec,
    *,
    reset: bool = False,
    locale: str = DEFAULT_LOCALE,
) -> str | None:
    """Apply a wizard spec to the companion and bring her to life.

    Returns her opening message. Raises `AlreadyOnboarded` if she is already live
    and `reset` was not requested.
    """
    async with sessionmaker() as session:
        comp = await session.get(Companion, companion_id)
        if comp is None:
            raise ValueError(f"Companion {companion_id} not found")
        if comp.onboarded_at is not None and not reset:
            raise AlreadyOnboarded(str(companion_id))
        # Creation always starts from zero. Besides an explicit reset this also
        # clears anything a lazily-created companion row may have accumulated
        # before the user ever chose who she is.
        await _wipe_history(session, companion_id)

        comp.name = spec.name
        comp.template_id = spec.template_id()
        comp.persona_spec = spec.model_dump()
        comp.avatar_path = resolve_avatar(spec)
        comp.locale = locale
        comp.onboarded_at = None  # set only once genesis actually succeeds
        await session.commit()

    # The row just changed and genesis reads it back through the session.
    runtime_cache.invalidate_companion(companion_id)

    result = await run_genesis(companion_id, sessionmaker=sessionmaker, spec=spec)

    async with sessionmaker() as session:
        comp = await session.get(Companion, companion_id)
        if comp is not None:
            comp.onboarded_at = datetime.now(UTC)
            await session.commit()
    runtime_cache.invalidate_companion(companion_id)

    log.info("companion_created", companion=spec.name, template=spec.template_id())
    return result.first_message
