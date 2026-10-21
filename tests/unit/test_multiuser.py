"""Accounts are isolated from each other.

This file is the regression guard for removing `resolve_singleton`. Before
accounts, every visitor and every Telegram chat converged on the oldest
companion row; if that behavior ever comes back, these fail.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect

import maya.web as web
from maya import runtime_cache
from maya.companions.singleton import resolve_for_user
from maya.db.models import Companion, Message, User
from tests.conftest import db_required


async def _make_user(sm, name: str) -> uuid.UUID:
    async with sm() as session:
        user = User(name=name)
        session.add(user)
        await session.commit()
        return user.id


@db_required
async def test_two_accounts_get_different_companions(db_sessionmaker):
    a = await _make_user(db_sessionmaker, "Ada")
    b = await _make_user(db_sessionmaker, "Grace")

    companion_a = await resolve_for_user(db_sessionmaker, user_id=a)
    companion_b = await resolve_for_user(db_sessionmaker, user_id=b)

    assert companion_a != companion_b
    async with db_sessionmaker() as session:
        owners = {c.id: c.user_id for c in (await session.scalars(select(Companion))).all()}
    assert owners == {companion_a: a, companion_b: b}


@db_required
async def test_resolution_is_stable_for_one_account(db_sessionmaker):
    a = await _make_user(db_sessionmaker, "Ada")
    first = await resolve_for_user(db_sessionmaker, user_id=a)
    runtime_cache.clear()  # prove it re-reads the same row, not just the cache
    assert await resolve_for_user(db_sessionmaker, user_id=a) == first


@db_required
async def test_resolution_creates_exactly_one_companion(db_sessionmaker):
    a = await _make_user(db_sessionmaker, "Ada")
    for _ in range(3):
        runtime_cache.clear()
        await resolve_for_user(db_sessionmaker, user_id=a)
    async with db_sessionmaker() as session:
        assert len((await session.scalars(select(Companion))).all()) == 1


@db_required
async def test_resolution_never_returns_another_accounts_companion(db_sessionmaker):
    """The specific old bug: picking the OLDEST companion regardless of owner."""
    a = await _make_user(db_sessionmaker, "First")
    companion_a = await resolve_for_user(db_sessionmaker, user_id=a)

    b = await _make_user(db_sessionmaker, "Second")
    companion_b = await resolve_for_user(db_sessionmaker, user_id=b)

    assert companion_b != companion_a


@db_required
async def test_messages_do_not_leak_between_accounts(db_sessionmaker):
    a = await _make_user(db_sessionmaker, "Ada")
    b = await _make_user(db_sessionmaker, "Grace")
    companion_a = await resolve_for_user(db_sessionmaker, user_id=a)
    companion_b = await resolve_for_user(db_sessionmaker, user_id=b)

    from maya.conversation.rooms import load_transcript, solo_conversation_id

    room_a = await solo_conversation_id(db_sessionmaker, companion_a)
    room_b = await solo_conversation_id(db_sessionmaker, companion_b)
    assert room_a != room_b
    async with db_sessionmaker() as session:
        session.add(
            Message(
                conversation_id=room_a,
                companion_id=companion_a,
                user_id=a,
                role="user",
                content="ada's secret",
            )
        )
        session.add(
            Message(
                conversation_id=room_b,
                companion_id=companion_b,
                user_id=b,
                role="user",
                content="grace's secret",
            )
        )
        await session.commit()

    # The /ws history replay reads the solo room; that must be enough.
    a_history = [m.content for m in await load_transcript(db_sessionmaker, room_a, 50)]
    assert a_history == ["ada's secret"]


@db_required
async def test_deleting_an_account_takes_its_companion_with_it(db_sessionmaker):
    a = await _make_user(db_sessionmaker, "Ada")
    await resolve_for_user(db_sessionmaker, user_id=a)
    async with db_sessionmaker() as session:
        user = await session.get(User, a)
        await session.delete(user)
        await session.commit()
    async with db_sessionmaker() as session:
        assert (await session.scalars(select(Companion))).all() == []


# ─────────────────────────── websocket auth ────────────────────────────────


def test_websocket_closes_4401_without_a_session(monkeypatch):
    """The SPA distinguishes 'session expired' from 'server down' by this code,
    and stops its 2s reconnect loop only on 4401.

    The socket is accepted first and then closed — a refused handshake would
    reach the browser with no readable code at all.
    """
    monkeypatch.setattr(web, "user_id_from_websocket", AsyncMock(return_value=None))
    with TestClient(web.app) as client, client.websocket_connect("/ws") as ws:
        with pytest.raises(WebSocketDisconnect) as caught:
            ws.receive_json()
    assert caught.value.code == web.WS_UNAUTHENTICATED


def test_websocket_resolves_the_socket_owners_companion(monkeypatch):
    """An authenticated socket must load the cookie-holder's companion, not a
    global one."""
    user_id = uuid.uuid4()
    seen: dict[str, uuid.UUID] = {}

    class _StopHere(Exception):
        """Ends the handler at the point of interest, before history replay."""

    async def _resolve(_sessionmaker, *, user_id: uuid.UUID) -> uuid.UUID:
        seen["user_id"] = user_id
        raise _StopHere

    monkeypatch.setattr(web, "user_id_from_websocket", AsyncMock(return_value=user_id))
    monkeypatch.setattr(web, "resolve_for_user", _resolve)

    with TestClient(web.app) as client, pytest.raises(_StopHere):
        with client.websocket_connect("/ws"):
            pass

    assert seen["user_id"] == user_id
