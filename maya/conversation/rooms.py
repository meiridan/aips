"""Conversations: which transcript a message belongs to.

A solo chat is a one-member room, created lazily the first time a companion
needs to read or write her transcript. A group room holds the account's own
companion plus a partner (Lila); it is created by
:func:`maya.companions.singleton.resolve_group`, which also brings the partner to
life.

This module deliberately imports nothing that calls an LLM, so genesis and the
orchestrator can both depend on it.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, select, update

from maya import runtime_cache
from maya.conversation.addressing import Addressable
from maya.db.models import Companion, Conversation, ConversationMember, Message

KIND_SOLO = "solo"
KIND_GROUP = "group"
SLOT_PRIMARY = "primary"

# One process, one event loop (see runtime_cache): a lock per companion is
# enough to stop two concurrent first turns creating two solo rooms.
_solo_locks: dict[uuid.UUID, asyncio.Lock] = {}


@dataclass(frozen=True)
class Member:
    """A companion as a room sees her."""

    companion_id: uuid.UUID
    slot: str
    name: str
    avatar_path: str | None = None
    #: Latin handle from the catalog ("maya", "lila") — a second name to address her by.
    handle: str | None = None

    def addressable(self) -> Addressable:
        names = tuple(n for n in (self.name, self.handle) if n)
        return Addressable(companion_id=self.companion_id, slot=self.slot, names=names)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.companion_id),
            "slot": self.slot,
            "name": self.name,
            "avatar_path": self.avatar_path,
        }


@dataclass(frozen=True)
class GroupRoom:
    conversation_id: uuid.UUID
    user_id: uuid.UUID
    members: tuple[Member, ...]
    dynamics: dict[str, Any] = field(default_factory=dict)
    #: What the user picked in the room (see `group_settings.GroupSettings`).
    settings: dict[str, Any] = field(default_factory=dict)

    def member(self, companion_id: uuid.UUID | None) -> Member | None:
        return next((m for m in self.members if m.companion_id == companion_id), None)

    def by_slot(self, slot: str) -> Member | None:
        return next((m for m in self.members if m.slot == slot), None)


def member_from(companion: Companion) -> Member:
    spec = companion.persona_spec or {}
    return Member(
        companion_id=companion.id,
        slot=companion.slot,
        name=companion.name,
        avatar_path=companion.avatar_path,
        handle=spec.get("preset") if isinstance(spec, dict) else None,
    )


async def solo_conversation_id(sessionmaker: Any, companion_id: uuid.UUID) -> uuid.UUID:
    """The companion's 1:1 room, created on first use. Immutable, so cached."""
    cached = runtime_cache.get_solo_conversation(companion_id)
    if cached is not None:
        return cached

    lock = _solo_locks.setdefault(companion_id, asyncio.Lock())
    async with lock:
        cached = runtime_cache.get_solo_conversation(companion_id)
        if cached is not None:
            return cached
        async with sessionmaker() as session:
            conversation_id = (
                await session.execute(
                    select(Conversation.id)
                    .join(ConversationMember, ConversationMember.conversation_id == Conversation.id)
                    .where(ConversationMember.companion_id == companion_id)
                    .where(Conversation.kind == KIND_SOLO)
                    .order_by(Conversation.created_at.asc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if conversation_id is None:
                companion = await session.get(Companion, companion_id)
                if companion is None:
                    raise ValueError(f"Companion {companion_id} not found")
                room = Conversation(user_id=companion.user_id, kind=KIND_SOLO)
                session.add(room)
                await session.flush()
                session.add(ConversationMember(conversation_id=room.id, companion_id=companion_id))
                await session.commit()
                conversation_id = room.id

    runtime_cache.set_solo_conversation(companion_id, conversation_id)
    return conversation_id


async def group_conversation_id(sessionmaker: Any, user_id: uuid.UUID) -> uuid.UUID | None:
    """The account's group room if it exists. Read-only: never creates one."""
    async with sessionmaker() as session:
        return (
            await session.execute(
                select(Conversation.id)
                .where(Conversation.user_id == user_id)
                .where(Conversation.kind == KIND_GROUP)
                .order_by(Conversation.created_at.asc())
                .limit(1)
            )
        ).scalar_one_or_none()


async def save_settings(
    sessionmaker: Any, conversation_id: uuid.UUID, settings: dict[str, Any]
) -> None:
    """Persist a room's UI settings (the whole dict — it is small and validated)."""
    async with sessionmaker() as session:
        await session.execute(
            update(Conversation).where(Conversation.id == conversation_id).values(settings=settings)
        )
        await session.commit()


async def load_transcript(
    sessionmaker: Any, conversation_id: uuid.UUID, limit: int
) -> list[Message]:
    """The newest `limit` messages of a room, in chronological order."""
    async with sessionmaker() as session:
        rows = list(
            (
                await session.scalars(
                    select(Message)
                    .where(Message.conversation_id == conversation_id)
                    .order_by(Message.created_at.desc())
                    .limit(limit)
                )
            ).all()
        )
    rows.reverse()
    return rows


async def wipe_group_rooms(session: Any, companion_id: uuid.UUID) -> None:
    """Clear the transcript of every group room she is in.

    Used when her own history is wiped (a wizard re-creation): deleting only her
    lines would leave the partner answering things nobody said.
    """
    rooms = (
        select(ConversationMember.conversation_id)
        .join(Conversation, Conversation.id == ConversationMember.conversation_id)
        .where(ConversationMember.companion_id == companion_id)
        .where(Conversation.kind == KIND_GROUP)
    )
    await session.execute(delete(Message).where(Message.conversation_id.in_(rooms)))
