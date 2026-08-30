"""Forgot-password and reset, end to end against real Postgres."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

import maya.api.auth as auth_api
import maya.auth.deps as deps
import maya.auth.sessions as sessions_mod
import maya.web as web
from maya.auth import accounts, ratelimit, reset
from maya.db.models import PasswordResetToken
from tests.conftest import db_required

pytestmark = db_required

EMAIL = "someone@example.com"
PASSWORD = "correct-horse-battery"
NEW_PASSWORD = "a-brand-new-secret"


@pytest_asyncio.fixture
async def client(db_sessionmaker, monkeypatch):
    for module in (auth_api, deps):
        monkeypatch.setattr(module, "get_sessionmaker", lambda: db_sessionmaker)
    ratelimit.reset()
    transport = httpx.ASGITransport(app=web.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def sent(monkeypatch):
    """Capture what would have been emailed."""
    outbox: list[tuple[str, str]] = []

    async def _send(to: str, url: str) -> bool:
        outbox.append((to, url))
        return True

    monkeypatch.setattr(auth_api, "send_password_reset", _send)
    return outbox


async def _signup(client):
    return await client.post("/api/auth/signup", json={"email": EMAIL, "password": PASSWORD})


def _token_from(url: str) -> str:
    return url.split("token=", 1)[1]


# ─────────────────────────── forgot-password ───────────────────────────────


async def test_forgot_password_sends_a_link_for_a_real_account(client, sent):
    await _signup(client)
    resp = await client.post("/api/auth/forgot-password", json={"email": EMAIL})
    assert resp.status_code == 202
    assert resp.json() == {"ok": True}
    assert len(sent) == 1
    assert "token=" in sent[0][1]


async def test_forgot_password_is_identical_for_an_unknown_address(client, sent):
    """The response must not distinguish a real account from a made-up one."""
    await _signup(client)
    known = await client.post("/api/auth/forgot-password", json={"email": EMAIL})
    unknown = await client.post("/api/auth/forgot-password", json={"email": "nobody@example.com"})
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    # ...and nothing was actually sent for the address that doesn't exist.
    assert [to for to, _ in sent] == [EMAIL]


async def test_forgot_password_accepts_a_malformed_address_silently(client, sent):
    resp = await client.post("/api/auth/forgot-password", json={"email": "not-an-email"})
    assert resp.status_code == 202
    assert sent == []


async def test_forgot_password_is_rate_limited_per_email(client, sent):
    await _signup(client)
    codes = []
    for _ in range(ratelimit.FORGOT_PASSWORD_PER_EMAIL.limit + 1):
        resp = await client.post("/api/auth/forgot-password", json={"email": EMAIL})
        codes.append(resp.status_code)
    assert codes[0] == 202
    assert codes[-1] == 429


async def test_requesting_again_retires_the_previous_link(client, sent, db_sessionmaker):
    """An older email sitting in an inbox must stop working."""
    await _signup(client)
    await client.post("/api/auth/forgot-password", json={"email": EMAIL})
    await client.post("/api/auth/forgot-password", json={"email": EMAIL})

    first, second = _token_from(sent[0][1]), _token_from(sent[1][1])
    assert await reset.consume(db_sessionmaker, first, NEW_PASSWORD) is False
    assert await reset.consume(db_sessionmaker, second, NEW_PASSWORD) is True


# ───────────────────────────── reset-password ──────────────────────────────


async def test_reset_sets_the_new_password(client, sent, db_sessionmaker):
    await _signup(client)
    await client.post("/api/auth/forgot-password", json={"email": EMAIL})
    token = _token_from(sent[0][1])

    resp = await client.post(
        "/api/auth/reset-password", json={"token": token, "password": NEW_PASSWORD}
    )
    assert resp.status_code == 200

    assert await accounts.authenticate(db_sessionmaker, EMAIL, NEW_PASSWORD) is not None
    assert await accounts.authenticate(db_sessionmaker, EMAIL, PASSWORD) is None


async def test_the_new_password_logs_in(client, sent):
    await _signup(client)
    await client.post("/api/auth/forgot-password", json={"email": EMAIL})
    await client.post(
        "/api/auth/reset-password",
        json={"token": _token_from(sent[0][1]), "password": NEW_PASSWORD},
    )
    resp = await client.post("/api/auth/login", json={"email": EMAIL, "password": NEW_PASSWORD})
    assert resp.status_code == 200


async def test_a_token_cannot_be_used_twice(client, sent):
    await _signup(client)
    await client.post("/api/auth/forgot-password", json={"email": EMAIL})
    token = _token_from(sent[0][1])

    first = await client.post(
        "/api/auth/reset-password", json={"token": token, "password": NEW_PASSWORD}
    )
    second = await client.post(
        "/api/auth/reset-password", json={"token": token, "password": "yet-another-one"}
    )
    assert first.status_code == 200
    assert second.status_code == 400
    assert second.json()["detail"] == "invalid_or_expired_token"


async def test_an_expired_token_is_rejected(client, sent, db_sessionmaker):
    await _signup(client)
    await client.post("/api/auth/forgot-password", json={"email": EMAIL})
    token = _token_from(sent[0][1])

    async with db_sessionmaker() as s:
        row = (await s.scalars(select(PasswordResetToken))).one()
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await s.commit()

    resp = await client.post(
        "/api/auth/reset-password", json={"token": token, "password": NEW_PASSWORD}
    )
    assert resp.status_code == 400


@pytest.mark.parametrize("token", ["", "not-a-real-token"])
async def test_a_bogus_token_is_rejected(client, token):
    resp = await client.post(
        "/api/auth/reset-password", json={"token": token, "password": NEW_PASSWORD}
    )
    assert resp.status_code == 400


async def test_a_weak_new_password_is_refused(client, sent):
    await _signup(client)
    await client.post("/api/auth/forgot-password", json={"email": EMAIL})
    resp = await client.post(
        "/api/auth/reset-password", json={"token": _token_from(sent[0][1]), "password": "short"}
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "password_too_short"


async def test_reset_revokes_every_existing_session(client, sent, db_sessionmaker):
    """The whole point: whoever else holds a cookie is logged out too."""
    await _signup(client)
    stolen = await sessions_mod.issue(
        db_sessionmaker, (await accounts.get_by_email(db_sessionmaker, EMAIL)).id
    )
    assert await sessions_mod.resolve(db_sessionmaker, stolen) is not None

    await client.post("/api/auth/forgot-password", json={"email": EMAIL})
    await client.post(
        "/api/auth/reset-password",
        json={"token": _token_from(sent[0][1]), "password": NEW_PASSWORD},
    )

    assert await sessions_mod.resolve(db_sessionmaker, stolen) is None
    # The caller's own session went too.
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_the_raw_token_is_never_stored(client, sent, db_sessionmaker):
    await _signup(client)
    await client.post("/api/auth/forgot-password", json={"email": EMAIL})
    token = _token_from(sent[0][1])
    async with db_sessionmaker() as s:
        stored = [r.token_hash for r in (await s.scalars(select(PasswordResetToken))).all()]
    assert token not in stored
