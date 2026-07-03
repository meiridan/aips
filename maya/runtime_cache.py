"""Process-local caches for the single-user app.

Maya is single-user by product decision (one shared companion for web +
Telegram, one uvicorn worker — see maya.companions.singleton and the Procfile).
That makes in-process caching safe and invalidation trivial: there is exactly
one process, one event loop, and rarely-changing identity/companion rows.

We only cache things that are effectively immutable per process life or change
on an explicit, rare write:
  - the resolved (user_id, companion_id) singleton — immutable once created
  - the Companion row — invalidated on the few write paths (genesis, CLI)
  - the user's display name — effectively constant

We deliberately do NOT cache emotional/relationship state: those are
read-modify-write every turn (lazy decay, interaction counters).
"""

from __future__ import annotations

import uuid
from typing import Any

# Resolved singleton identity: (user_id, companion_id). Immutable once set.
_singleton: tuple[uuid.UUID, uuid.UUID] | None = None

# Companion row keyed by companion_id (SQLAlchemy instance, detached/expunged).
_companions: dict[uuid.UUID, Any] = {}

# User display name keyed by user_id.
_user_names: dict[uuid.UUID, str] = {}


def get_singleton() -> tuple[uuid.UUID, uuid.UUID] | None:
    return _singleton


def set_singleton(user_id: uuid.UUID, companion_id: uuid.UUID) -> None:
    global _singleton
    _singleton = (user_id, companion_id)


def get_companion(companion_id: uuid.UUID) -> Any | None:
    return _companions.get(companion_id)


def set_companion(companion_id: uuid.UUID, companion: Any) -> None:
    _companions[companion_id] = companion


def invalidate_companion(companion_id: uuid.UUID) -> None:
    _companions.pop(companion_id, None)


def get_user_name(user_id: uuid.UUID) -> str | None:
    return _user_names.get(user_id)


def set_user_name(user_id: uuid.UUID, name: str) -> None:
    _user_names[user_id] = name


def clear() -> None:
    """Drop every cached value. For tests and manual invalidation."""
    global _singleton
    _singleton = None
    _companions.clear()
    _user_names.clear()
