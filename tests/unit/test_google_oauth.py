"""Google sign-in, with Google itself faked at the httpx layer.

Follows the `_FakeAsyncClient` pattern from test_telegram.py: no network, and
the assertions are about what we send Google and what we do with what comes
back.
"""

from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

import maya.api.auth as auth_api
import maya.api.google_auth as google_api
import maya.auth.deps as deps
import maya.auth.google as google_mod
import maya.web as web
from maya.auth import accounts, ratelimit
from maya.db.models import User
from tests.conftest import db_required

pytestmark = db_required

SUB = "116_google_subject"
EMAIL = "someone@example.com"


@pytest.fixture(autouse=True)
def _configured(monkeypatch):
    """Pretend the OAuth client is set up."""
    from maya.config import Settings, get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-id.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://maya.example.com")
    yield Settings()
    get_settings.cache_clear()


@pytest.fixture
def google_says(monkeypatch):
    """Install a fake Google. Returns a dict the test can edit."""
    claims = {"sub": SUB, "email": EMAIL, "email_verified": True, "name": "Ada Lovelace"}
    calls: dict[str, dict] = {}

    class _FakeAsyncClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, data=None, **kw):
            calls["token"] = data or {}
            return httpx.Response(200, json={"access_token": "ya29.fake"})

        async def get(self, url, headers=None, **kw):
            calls["userinfo_headers"] = headers or {}
            return httpx.Response(200, json=claims)

    monkeypatch.setattr(google_mod.httpx, "AsyncClient", _FakeAsyncClient)
    return {"claims": claims, "calls": calls}


@pytest_asyncio.fixture
async def client(db_sessionmaker, monkeypatch):
    for module in (auth_api, deps, google_api):
        monkeypatch.setattr(module, "get_sessionmaker", lambda: db_sessionmaker)
    ratelimit.reset()
    transport = httpx.ASGITransport(app=web.app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", follow_redirects=False
    ) as c:
        yield c


async def _start(client):
    """Run /start and return the state the server handed the browser."""
    resp = await client.get("/auth/google/start")
    assert resp.status_code == 302
    return httpx.URL(resp.headers["location"]).params["state"]


# ───────────────────────────── the start leg ───────────────────────────────


async def test_start_redirects_to_google_with_pkce(client):
    resp = await client.get("/auth/google/start")
    assert resp.status_code == 302
    url = httpx.URL(resp.headers["location"])
    assert str(url).startswith(google_mod.AUTH_ENDPOINT)
    assert url.params["code_challenge_method"] == "S256"
    assert url.params["code_challenge"]
    assert url.params["scope"] == "openid email profile"
    # Otherwise a signed-in Google user can never pick a different account.
    assert url.params["prompt"] == "select_account"


async def test_start_sets_httponly_flow_cookies(client):
    resp = await client.get("/auth/google/start")
    jar = "; ".join(resp.headers.get_list("set-cookie")).lower()
    assert google_mod.STATE_COOKIE in jar
    assert google_mod.VERIFIER_COOKIE in jar
    assert jar.count("httponly") >= 2


def test_challenge_is_the_s256_of_the_verifier():
    import base64
    import hashlib

    verifier = "a-known-verifier"
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    assert google_mod.challenge_for(verifier) == expected


# ─────────────────────────── the callback leg ──────────────────────────────


async def test_callback_creates_an_account(client, google_says, db_sessionmaker):
    state = await _start(client)
    resp = await client.get(f"/auth/google/callback?code=abc&state={state}")

    assert resp.status_code == 302
    assert resp.headers["location"] == "/"
    user = await accounts.get_by_google_sub(db_sessionmaker, SUB)
    assert user is not None and user.email == EMAIL
    assert user.email_verified_at is not None
    # No password was set, and none should have been invented.
    assert user.password_hash is None


async def test_callback_signs_the_browser_in(client, google_says):
    state = await _start(client)
    await client.get(f"/auth/google/callback?code=abc&state={state}")
    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == EMAIL


async def test_returning_user_is_matched_not_duplicated(client, google_says, db_sessionmaker):
    for _ in range(2):
        state = await _start(client)
        await client.get(f"/auth/google/callback?code=abc&state={state}")

    async with db_sessionmaker() as s:
        users = (await s.scalars(select(User))).all()
    assert len(users) == 1


async def test_google_links_to_an_existing_password_account(client, google_says, db_sessionmaker):
    """Signing in with Google must reach the same companion, not a second one."""
    await client.post("/api/auth/signup", json={"email": EMAIL, "password": "hunter2000000"})
    await client.post("/api/auth/logout")

    state = await _start(client)
    await client.get(f"/auth/google/callback?code=abc&state={state}")

    async with db_sessionmaker() as s:
        users = (await s.scalars(select(User))).all()
    assert len(users) == 1
    assert users[0].google_sub == SUB
    assert users[0].password_hash is not None  # the password still works


async def test_unverified_google_email_cannot_claim_an_account(
    client, google_says, db_sessionmaker
):
    """Otherwise anyone who can make Google report an address they don't own
    could take over the matching password account."""
    await client.post("/api/auth/signup", json={"email": EMAIL, "password": "hunter2000000"})
    await client.post("/api/auth/logout")
    google_says["claims"]["email_verified"] = False

    state = await _start(client)
    resp = await client.get(f"/auth/google/callback?code=abc&state={state}")

    assert resp.status_code == 400
    assert resp.json()["detail"] == "google_email_unverified"


async def test_mismatched_state_is_rejected(client, google_says, db_sessionmaker):
    """The CSRF guard: a callback the browser never initiated."""
    await _start(client)
    resp = await client.get("/auth/google/callback?code=abc&state=not-the-one")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "invalid_oauth_state"
    async with db_sessionmaker() as s:
        assert (await s.scalars(select(User))).all() == []


async def test_callback_without_the_flow_cookies_is_rejected(client, google_says):
    resp = await client.get("/auth/google/callback?code=abc&state=anything")
    assert resp.status_code == 400


@pytest.mark.parametrize("query", ["", "?state=x", "?code=abc"])
async def test_callback_requires_both_parameters(client, google_says, query):
    await _start(client)
    assert (await client.get(f"/auth/google/callback{query}")).status_code == 400


async def test_verifier_is_sent_to_google(client, google_says):
    """PKCE is pointless if the verifier never reaches the token exchange."""
    state = await _start(client)
    await client.get(f"/auth/google/callback?code=abc&state={state}")
    assert google_says["calls"]["token"]["code_verifier"]
    assert google_says["calls"]["token"]["grant_type"] == "authorization_code"
    assert google_says["calls"]["userinfo_headers"]["Authorization"] == "Bearer ya29.fake"


async def test_callback_is_rate_limited(client, google_says):
    codes = []
    for _ in range(ratelimit.GOOGLE_CALLBACK.limit + 1):
        codes.append((await client.get("/auth/google/callback?code=a&state=b")).status_code)
    assert codes[-1] == 429


async def test_start_redirects_to_login_when_google_is_not_configured(client, monkeypatch):
    """This URL is reached by clicking a link, so a raw JSON body would be a
    dead end for whoever clicked."""
    from maya.config import get_settings

    get_settings.cache_clear()
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    try:
        resp = await client.get("/auth/google/start")
        assert resp.status_code == 302
        assert resp.headers["location"] == "/login?error=google_not_configured"
    finally:
        get_settings.cache_clear()


async def test_callback_is_503_when_google_is_not_configured(client, monkeypatch):
    """Not a normal navigation — reaching it unconfigured means a crafted URL."""
    from maya.config import get_settings

    get_settings.cache_clear()
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    try:
        assert (await client.get("/auth/google/callback?code=a&state=b")).status_code == 503
    finally:
        get_settings.cache_clear()


async def test_catalog_advertises_google_availability(client):
    """What the SPA uses to decide whether to render the button at all."""
    body = (await client.get("/api/catalog")).json()
    assert body["auth"]["google"] is True
