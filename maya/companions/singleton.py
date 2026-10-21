"""Companion and room resolution, per account.

This module used to resolve ONE shared Maya for the whole app (the oldest
companion row), because Maya was single-user by product decision. Accounts
changed that: the web channel resolves the signed-in user's companion, and
Telegram resolves the companion belonging to the chat it is talking to.

The two channels differ in one way that matters. The web UI has a creation
wizard, so a new account's companion is an empty row until the wizard submits a
spec and pays for genesis. Telegram has no wizard, so a first-time chat has to
bring a default companion to life immediately or it would answer with nothing.

An account can now own more than one companion: its own ("primary" slot) and a
group-chat partner per partner slot (e.g. "lila"). `resolve_for_user` only ever
returns the primary one; `resolve_group` builds the room the two share.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from maya import runtime_cache
from maya.companions import catalog
from maya.companions.avatars import resolve_avatar
from maya.companions.genesis import run_genesis
from maya.companions.persona_spec import PersonaSpec
from maya.conversation.rooms import (
    KIND_GROUP,
    SLOT_PRIMARY,
    GroupRoom,
    member_from,
)
from maya.db.models import Companion, Conversation, ConversationMember, User
from maya.db.session import get_sessionmaker
from maya.logging import get_logger

log = get_logger("maya.singleton")

# Creating a partner pays for a genesis call; two tabs opening the group chat at
# once must not pay twice. One process (see runtime_cache), so a dict of locks.
_group_locks: dict[uuid.UUID, asyncio.Lock] = {}


class CompanionNotOnboarded(RuntimeError):
    """The account's own companion does not exist yet, so there is no room to join."""


async def resolve_for_user(
    sessionmaker: Any = None,
    *,
    user_id: uuid.UUID,
) -> uuid.UUID:
    """Return the account's own companion id, creating an empty one if needed.

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
                .where(Companion.slot == SLOT_PRIMARY)
                .order_by(Companion.created_at.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if comp is None:
            comp = Companion(user_id=user_id, name="Maya", template_id="flirt", slot=SLOT_PRIMARY)
            session.add(comp)
            await session.commit()
        companion_id = comp.id

    runtime_cache.set_companion_for_user(user_id, companion_id)
    return companion_id


async def resolve_group(
    sessionmaker: Any = None,
    *,
    user_id: uuid.UUID,
    partner_id: str = catalog.DEFAULT_GROUP_PARTNER,
) -> GroupRoom:
    """The account's group room with its companion and `partner_id`.

    First call creates the partner's companion row, runs her genesis (one main
    LLM call, her opener lands in the room) and the room itself. Later calls
    only read. Raises `CompanionNotOnboarded` before the account's own companion
    exists — the room is "her and her friend", so she has to come first.
    """
    partner = catalog.group_partner(partner_id)
    if partner is None:
        raise ValueError(f"unknown group partner: {partner_id!r}")
    sm = sessionmaker or get_sessionmaker()
    primary_id = await resolve_for_user(sm, user_id=user_id)

    lock = _group_locks.setdefault(user_id, asyncio.Lock())
    async with lock:
        spec = PersonaSpec(name=partner.name, preset=partner.id, **partner.spec)
        async with sm() as session:
            primary = await session.get(Companion, primary_id)
            if primary is None or primary.onboarded_at is None:
                raise CompanionNotOnboarded(str(primary_id))
            user = await session.get(User, user_id)
            user_name = user.name if user else "him"

            mate = (
                await session.execute(
                    select(Companion)
                    .where(Companion.user_id == user_id)
                    .where(Companion.slot == partner.id)
                )
            ).scalar_one_or_none()
            if mate is None:
                mate = Companion(
                    user_id=user_id,
                    slot=partner.id,
                    name=spec.name,
                    template_id=spec.template_id(),
                    persona_spec=spec.model_dump(),
                    avatar_path=resolve_avatar(spec),
                    locale=primary.locale,
                )
                session.add(mate)

            room = (
                await session.execute(
                    select(Conversation)
                    .where(Conversation.user_id == user_id)
                    .where(Conversation.kind == KIND_GROUP)
                    .order_by(Conversation.created_at.asc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if room is None:
                room = Conversation(
                    user_id=user_id,
                    kind=KIND_GROUP,
                    dynamics={"partner": partner.id, "description": partner.dynamics},
                )
                session.add(room)
            await session.flush()

            present = set(
                (
                    await session.scalars(
                        select(ConversationMember.companion_id).where(
                            ConversationMember.conversation_id == room.id
                        )
                    )
                ).all()
            )
            for position, companion_id in enumerate((primary.id, mate.id)):
                if companion_id not in present:
                    session.add(
                        ConversationMember(
                            conversation_id=room.id, companion_id=companion_id, position=position
                        )
                    )
            await session.commit()
            room_id, mate_id = room.id, mate.id
            needs_genesis = mate.onboarded_at is None
            primary_name = primary.name

        if needs_genesis:
            context = catalog.fill_names(
                partner.genesis_context, primary=primary_name, partner=spec.name, user=user_name
            )
            await run_genesis(
                mate_id,
                sessionmaker=sm,
                spec=spec,
                conversation_id=room_id,
                group_context=context,
            )
            async with sm() as session:
                row = await session.get(Companion, mate_id)
                if row is not None:
                    row.onboarded_at = datetime.now(UTC)
                    await session.commit()
            runtime_cache.invalidate_companion(mate_id)
            log.info("group_partner_created", partner=partner.id, user_id=str(user_id))

    return await load_room(sm, room_id)


async def load_room(sessionmaker: Any, conversation_id: uuid.UUID) -> GroupRoom:
    """A room with its members in seat order."""
    async with sessionmaker() as session:
        room = await session.get(Conversation, conversation_id)
        if room is None:
            raise ValueError(f"Conversation {conversation_id} not found")
        rows = (
            (
                await session.execute(
                    select(Companion)
                    .join(ConversationMember, ConversationMember.companion_id == Companion.id)
                    .where(ConversationMember.conversation_id == conversation_id)
                    .order_by(ConversationMember.position.asc())
                )
            )
            .scalars()
            .all()
        )
        return GroupRoom(
            conversation_id=room.id,
            user_id=room.user_id,
            members=tuple(member_from(c) for c in rows),
            dynamics=dict(room.dynamics or {}),
            settings=dict(room.settings or {}),
        )


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
            await session.execute(
                select(Companion.id)
                .where(Companion.user_id == user_id)
                .where(Companion.slot == SLOT_PRIMARY)
                .limit(1)
            )
        ).scalar_one_or_none() is not None
