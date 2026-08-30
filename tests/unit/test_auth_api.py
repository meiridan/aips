"""Signup / login / logout / me over the real router, against real Postgres.

Unlike the older wizard tests, these do not monkeypatch the data layer: the
whole point of an auth endpoint is what it writes and reads back.

They drive the app through `httpx.ASGITransport` rather than `TestClient`
because TestClient runs the app in its own thread and event loop, while the
`db_sessionmaker` fixture's asyncpg connections belong to the test's loop —
mixing the two raises "another operation is in progress".
"""

from __future__ import annotations

import httpx
import pytest
import pytest_asyncio

import maya.api.auth as auth_api
import maya.auth.deps as deps
import maya.auth.sessions as sessions_mod
import maya.web as web
from maya.auth import accounts, ratelimit
from tests.conftest import db_required

pytestmark = db_required

EMAIL = "Someone@Example.com"
PASSWORD = "correct-horse-battery"


@pytest_asyncio.fixture
async def client(db_sessionmaker, monkeypatch):
    """An async client whose auth stack talks to the isolated test database."""
    # sessions.py takes its sessionmaker as an argument; only these two reach
    # for the global one.
    for module in (auth_api, deps):
        monkeypatch.setattr(module, "get_sessionmaker", lambda: db_sessionmaker)
    ratelimit.reset()
    transport = httpx.ASGITransport(app=web.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def signup(client, email=EMAIL, password=PASSWORD):
    return await client.post("/api/auth/signup", json={"email": email, "password": password})


async def test_signup_creates_an_account_and_signs_in(client):
    resp = await signup(client)
    assert resp.status_code == 201
    assert resp.json()["user"]["email"] == EMAIL
    assert sessions_mod.COOKIE_NAME in resp.cookies
    me = await client.get("/api/auth/me")
    assert me.json()["user"]["email"] == EMAIL


async def test_signup_never_returns_the_password_hash(client):
    body = (await signup(client)).json()
    assert "password" not in str(body) and "scrypt" not in str(body)
    assert set(body["user"]) == {"id", "email", "name", "email_verified"}


async def test_session_cookie_is_httponly_and_lax(client):
    resp = await signup(client)
    cookie_header = resp.headers["set-cookie"].lower()
    assert "httponly" in cookie_header
    assert "samesite=lax" in cookie_header


async def test_duplicate_email_is_409_case_insensitively(client):
    await signup(client)
    resp = await signup(client, email="someone@example.com")
    assert resp.status_code == 409
    assert resp.json()["detail"] == "email_taken"


@pytest.mark.parametrize(
    "email,password,detail",
    [
        ("nope", PASSWORD, "email_invalid"),
        ("", PASSWORD, "email_required"),
        (EMAIL, "short", "password_too_short"),
        (EMAIL, "x" * 500, "password_too_long"),
    ],
)
async def test_signup_validation(client, email, password, detail):
    resp = await signup(client, email=email, password=password)
    assert resp.status_code == 422
    assert resp.json()["detail"] == detail


async def test_login_succeeds_with_correct_credentials(client):
    await signup(client)
    await client.post("/api/auth/logout")
    resp = await client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert resp.status_code == 200
    assert (await client.get("/api/auth/me")).status_code == 200


async def test_login_is_case_insensitive_and_trims(client):
    await signup(client)
    await client.post("/api/auth/logout")
    resp = await client.post(
        "/api/auth/login", json={"email": "  SOMEONE@EXAMPLE.COM  ", "password": PASSWORD}
    )
    assert resp.status_code == 200


async def test_unknown_user_and_wrong_password_are_indistinguishable(client):
    """If these differ, the endpoint becomes an account-existence oracle."""
    await signup(client)
    await client.post("/api/auth/logout")

    wrong = await client.post("/api/auth/login", json={"email": EMAIL, "password": "wrong-one"})
    unknown = await client.post(
        "/api/auth/login", json={"email": "nobody@example.com", "password": "wrong-one"}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": "invalid_credentials"}


async def test_logout_revokes_the_session(client):
    await signup(client)
    assert (await client.post("/api/auth/logout")).status_code == 200
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_logout_is_idempotent(client):
    assert (await client.post("/api/auth/logout")).status_code == 200


async def test_me_is_401_when_signed_out(client):
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_a_revoked_cookie_stops_working(client):
    """Presenting a stale but well-formed cookie must fail."""
    await signup(client)
    token = client.cookies[sessions_mod.COOKIE_NAME]
    await client.post("/api/auth/logout")
    client.cookies.set(sessions_mod.COOKIE_NAME, token)
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_login_rate_limit_returns_429(client):
    await signup(client)
    await client.post("/api/auth/logout")
    codes = []
    for _ in range(ratelimit.LOGIN.limit + 2):
        resp = await client.post("/api/auth/login", json={"email": EMAIL, "password": "wrong"})
        codes.append(resp.status_code)
    assert codes[0] == 401
    assert codes[-1] == 429


async def test_rate_limit_is_per_email(client):
    """One account being attacked must not lock everyone else out."""
    for _ in range(ratelimit.LOGIN.limit + 1):
        await client.post("/api/auth/login", json={"email": "victim@example.com", "password": "x"})
    other = await client.post(
        "/api/auth/login", json={"email": "bystander@example.com", "password": "x"}
    )
    assert other.status_code == 401


async def test_signup_does_not_create_a_companion(client, db_sessionmaker):
    """Genesis costs an LLM call; it belongs to the wizard, not to signup."""
    from sqlalchemy import select

    from maya.db.models import Companion

    await signup(client)
    async with db_sessionmaker() as s:
        assert (await s.scalars(select(Companion))).all() == []


async def test_account_name_is_derived_from_the_email(client, db_sessionmaker):
    await signup(client, email="ada.lovelace@example.com")
    user = await accounts.get_by_email(db_sessionmaker, "ada.lovelace@example.com")
    assert user is not None and user.name == "Ada Lovelace"


async def test_password_hash_is_stored_not_the_plaintext(client, db_sessionmaker):
    await signup(client)
    user = await accounts.get_by_email(db_sessionmaker, EMAIL)
    assert user is not None
    assert user.password_hash and PASSWORD not in user.password_hash
    assert user.password_hash.startswith("scrypt$")


# ───────────────────────────── dev autologin ───────────────────────────────


async def test_dev_autologin_serves_a_fixed_account_without_a_cookie(client, db_sessionmaker):
    """The local-only bypass: no cookie, still a real account behind /me."""
    assert (await client.get("/api/auth/me")).status_code == 401

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(deps, "dev_autologin_enabled", lambda: True)
        first = await client.get("/api/auth/me")
        second = await client.get("/api/auth/me")

    assert first.status_code == 200
    assert first.json()["user"]["email"] == deps.DEV_ACCOUNT_EMAIL
    # Get-or-create, not create-every-request: same row both times.
    assert second.json()["user"]["id"] == first.json()["user"]["id"]
    assert await accounts.get_by_email(db_sessionmaker, deps.DEV_ACCOUNT_EMAIL) is not None


def test_dev_autologin_is_ignored_outside_a_local_environment(monkeypatch):
    """A leaked env var must not open a deployed instance up."""
    from maya.config import Settings

    monkeypatch.setattr(
        deps, "get_settings", lambda: Settings(dev_autologin=True, environment="production")
    )
    assert deps.dev_autologin_enabled() is False

    monkeypatch.setattr(
        deps, "get_settings", lambda: Settings(dev_autologin=True, environment="local")
    )
    assert deps.dev_autologin_enabled() is True
