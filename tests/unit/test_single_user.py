"""Single-user mode: no login flow, one account, no quota.

SINGLE_USER is the app's default, but `tests/conftest._single_user_off` turns it
off for the suite so the auth tests stay meaningful. These turn it back on and
pin down what "no login" actually guarantees.

Driven through `httpx.ASGITransport` for the same reason as test_auth_api.py:
TestClient's own event loop can't share the fixture's asyncpg connections.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

import maya.auth.deps as deps
import maya.web as web
from maya.billing import entitlements
from maya.config import get_settings
from maya.db.models import Message, User
from tests.conftest import db_required

pytestmark = db_required


def _enable(monkeypatch, user_id: str = "") -> None:
    """Turn single-user mode on, optionally pinning a row."""
    monkeypatch.setenv("SINGLE_USER", "1")
    # Explicit empty rather than delenv: .env carries MAYA_SINGLE_USER_ID on the
    # dev machine and pydantic reads the file when the variable is absent.
    monkeypatch.setenv("MAYA_SINGLE_USER_ID", user_id)
    get_settings.cache_clear()
    deps.reset_solo_cache()


@pytest_asyncio.fixture
async def client(db_sessionmaker, monkeypatch):
    """A cookie-less client whose auth stack talks to the test database."""
    for module in (deps, web):
        monkeypatch.setattr(module, "get_sessionmaker", lambda: db_sessionmaker)
    _enable(monkeypatch)
    transport = httpx.ASGITransport(app=web.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_me_answers_without_a_session_cookie(client):
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 200
    assert resp.json()["user"]["email"] == deps.SOLO_ACCOUNT_EMAIL


async def test_the_wizard_api_needs_no_login(client):
    resp = await client.get("/api/companion")
    assert resp.status_code == 200
    assert resp.json()["onboarded"] is False


async def test_the_solo_account_is_created_once(client, db_sessionmaker):
    await client.get("/api/auth/me")
    deps.reset_solo_cache()  # prove it re-finds the row instead of adding another
    await client.get("/api/auth/me")
    async with db_sessionmaker() as session:
        assert len((await session.scalars(select(User.id))).all()) == 1


async def test_the_solo_account_has_no_password(client, db_sessionmaker):
    """It must stay unusable as a login even after SINGLE_USER goes away."""
    await client.get("/api/auth/me")
    user = await deps.accounts.get_by_email(db_sessionmaker, deps.SOLO_ACCOUNT_EMAIL)
    assert user is not None and user.password_hash is None


async def test_the_catalog_reports_the_mode(client):
    assert (await client.get("/api/catalog")).json()["auth"]["single_user"] is True


async def test_a_pinned_id_wins(client, db_sessionmaker, monkeypatch):
    async with db_sessionmaker() as session:
        pinned = User(name="Pinned")
        session.add(pinned)
        await session.commit()
        pinned_id = pinned.id

    _enable(monkeypatch, str(pinned_id))
    assert (await client.get("/api/auth/me")).json()["user"]["id"] == str(pinned_id)


async def test_a_stale_pinned_id_falls_back_to_the_sentinel(client, monkeypatch):
    """A leftover MAYA_SINGLE_USER_ID must not 500 every request."""
    _enable(monkeypatch, str(uuid.uuid4()))
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 200
    assert resp.json()["user"]["email"] == deps.SOLO_ACCOUNT_EMAIL


async def test_a_malformed_pinned_id_falls_back_to_the_sentinel(client, monkeypatch):
    _enable(monkeypatch, "not-a-uuid")
    assert (await client.get("/api/auth/me")).json()["user"]["email"] == deps.SOLO_ACCOUNT_EMAIL


async def test_the_websocket_resolves_a_user_without_a_cookie(db_sessionmaker, monkeypatch):
    """No cookie means no 4401 any more — the socket belongs to the solo user."""
    monkeypatch.setattr(deps, "get_sessionmaker", lambda: db_sessionmaker)
    _enable(monkeypatch)
    user_id = await deps.user_id_from_websocket(SimpleNamespace(cookies={}))
    assert user_id is not None


@pytest.mark.parametrize("single_user, expected", [(True, False), (False, True)])
async def test_quota_is_bypassed(db_sessionmaker, monkeypatch, seeded_ids, single_user, expected):
    """One shared account would otherwise lock the whole instance out at 30/day."""
    from maya.conversation.rooms import solo_conversation_id

    user_id, companion_id = seeded_ids
    conversation_id = await solo_conversation_id(db_sessionmaker, companion_id)
    async with db_sessionmaker() as session:
        for i in range(3):
            session.add(
                Message(
                    conversation_id=conversation_id,
                    companion_id=companion_id,
                    user_id=user_id,
                    role="user",
                    content=str(i),
                )
            )
        await session.commit()

    monkeypatch.setenv("SINGLE_USER", "1" if single_user else "0")
    monkeypatch.setenv("FREE_DAILY_MESSAGE_LIMIT", "2")
    get_settings.cache_clear()
    assert await entitlements.quota_exceeded(db_sessionmaker, user_id) is expected
