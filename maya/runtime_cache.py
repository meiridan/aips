"""Process-local caches.

The Procfile runs one uvicorn worker, so a module dict is a process-wide cache
with trivial invalidation: one process, one event loop, and rarely-changing
identity/companion rows. (If the app is ever scaled past one worker, these need
to move to the provisioned Upstash Redis.)

We only cache things that are effectively immutable per process life or change
on an explicit, rare write:
  - each account's companion id — immutable once created
  - each Telegram chat's account id — immutable once created
  - the Companion row — invalidated on the few write paths (genesis, CLI)
  - the user's display name — effectively constant

We deliberately do NOT cache emotional/relationship state: those are
read-modify-write every turn (lazy decay, interaction counters).

Nothing here is an authorization decision — sessions are looked up in Postgres
on every request, so a revoked login is never served from a cache.
"""

from __future__ import annotations

import uuid
from typing import Any

# user_id -> companion_id. Immutable once the companion row exists.
_companion_by_user: dict[uuid.UUID, uuid.UUID] = {}

# Telegram chat_id -> user_id. Immutable once the account exists.
_user_by_telegram_chat: dict[int, uuid.UUID] = {}

# Companion row keyed by companion_id (SQLAlchemy instance, detached/expunged).
_companions: dict[uuid.UUID, Any] = {}

# User display name keyed by user_id.
_user_names: dict[uuid.UUID, str] = {}

# companion_id -> her solo conversation id. Immutable once created.
_solo_conversations: dict[uuid.UUID, uuid.UUID] = {}


def get_companion_for_user(user_id: uuid.UUID) -> uuid.UUID | None:
    return _companion_by_user.get(user_id)


def set_companion_for_user(user_id: uuid.UUID, companion_id: uuid.UUID) -> None:
    _companion_by_user[user_id] = companion_id


def get_user_for_telegram_chat(chat_id: int) -> uuid.UUID | None:
    return _user_by_telegram_chat.get(chat_id)


def set_user_for_telegram_chat(chat_id: int, user_id: uuid.UUID) -> None:
    _user_by_telegram_chat[chat_id] = user_id


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


def get_solo_conversation(companion_id: uuid.UUID) -> uuid.UUID | None:
    return _solo_conversations.get(companion_id)


def set_solo_conversation(companion_id: uuid.UUID, conversation_id: uuid.UUID) -> None:
    _solo_conversations[companion_id] = conversation_id


def clear() -> None:
    """Drop every cached value. For tests and manual invalidation."""
    _companion_by_user.clear()
    _user_by_telegram_chat.clear()
    _companions.clear()
    _user_names.clear()
    _solo_conversations.clear()
