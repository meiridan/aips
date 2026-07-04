"""Per-companion runtime settings mutations (currently: response length).

Shared by every control surface (Telegram `/length`, web POST) so the write +
cache-invalidation lives in one place. The companion row is cached in
runtime_cache, so any write MUST invalidate it or the next turn reads stale."""

from __future__ import annotations

import uuid
from typing import Any

from maya import runtime_cache
from maya.conversation import response_length
from maya.db.models import Companion


async def set_response_length(
    sessionmaker: Any, companion_id: uuid.UUID, level: object
) -> int:
    """Persist the companion's reply-length level (normalized to 1–3).

    Returns the stored level. Invalidates the companion cache so the change
    takes effect on the next turn."""
    normalized = response_length.normalize(level)
    async with sessionmaker() as session:
        comp = await session.get(Companion, companion_id)
        if comp is None:
            raise ValueError(f"Companion {companion_id} not found")
        comp.response_length = normalized
        await session.commit()
    runtime_cache.invalidate_companion(companion_id)
    return normalized
