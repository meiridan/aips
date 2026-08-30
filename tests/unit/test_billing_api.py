"""Subscription endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import pytest_asyncio

import maya.api.auth as auth_api
import maya.api.billing as billing_api
import maya.auth.deps as deps
import maya.web as web
from maya.auth import ratelimit
from maya.billing import stripe_client
from maya.db.models import Subscription
from tests.conftest import db_required

pytestmark = db_required

EMAIL = "someone@example.com"
PASSWORD = "correct-horse-battery"


@pytest_asyncio.fixture
async def client(db_sessionmaker, monkeypatch):
    for module in (auth_api, deps, billing_api):
        monkeypatch.setattr(module, "get_sessionmaker", lambda: db_sessionmaker)
    ratelimit.reset()
    transport = httpx.ASGITransport(app=web.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def signed_in(client, db_sessionmaker):
    await client.post("/api/auth/signup", json={"email": EMAIL, "password": PASSWORD})
    from maya.auth import accounts

    user = await accounts.get_by_email(db_sessionmaker, EMAIL)
    return user.id


@pytest.fixture
def stripe_configured(monkeypatch):
    monkeypatch.setattr(stripe_client, "is_configured", lambda: True)


# ─────────────────────────────── plans ─────────────────────────────────────


async def test_plans_are_public(client):
    """Pricing should be visible before anyone signs up."""
    resp = await client.get("/api/subscription/plans")
    assert resp.status_code == 200
    ids = [p["id"] for p in resp.json()["plans"]]
    assert "free" in ids and "plus_monthly" in ids


async def test_plans_never_leak_stripe_price_ids(client):
    """The client picks by our id; the price mapping stays server-side."""
    body = await client.get("/api/subscription/plans")
    assert "price_" not in body.text
    assert "stripe" not in body.text.lower()


# ──────────────────────────── current status ───────────────────────────────


async def test_subscription_requires_a_session(client):
    assert (await client.get("/api/subscription")).status_code == 401


async def test_a_new_account_is_on_the_free_plan(client, signed_in):
    body = (await client.get("/api/subscription")).json()
    assert body["plan_id"] == "free"
    assert body["status"] == "inactive"
    assert body["manageable"] is False


async def test_an_active_subscription_is_reported(client, signed_in, db_sessionmaker):
    ends = datetime.now(UTC) + timedelta(days=12)
    async with db_sessionmaker() as s:
        s.add(
            Subscription(
                user_id=signed_in,
                plan_id="plus_monthly",
                status="active",
                current_period_end=ends,
                stripe_customer_id="cus_x",
            )
        )
        await s.commit()

    body = (await client.get("/api/subscription")).json()
    assert body["plan_id"] == "plus_monthly"
    assert body["status"] == "active"
    assert body["manageable"] is True
    assert body["current_period_end"].startswith(ends.isoformat()[:10])


# ─────────────────────────────── checkout ──────────────────────────────────


async def test_checkout_requires_a_session(client):
    resp = await client.post("/api/subscription/checkout", json={"plan_id": "plus_monthly"})
    assert resp.status_code == 401


async def test_checkout_rejects_an_unknown_plan(client, signed_in, stripe_configured):
    resp = await client.post("/api/subscription/checkout", json={"plan_id": "platinum"})
    assert resp.status_code == 422
    assert resp.json()["detail"] == "unknown_plan"


async def test_checkout_refuses_to_sell_the_free_plan(client, signed_in, stripe_configured):
    resp = await client.post("/api/subscription/checkout", json={"plan_id": "free"})
    assert resp.status_code == 422


async def test_checkout_is_503_when_stripe_is_not_configured(client, signed_in):
    resp = await client.post("/api/subscription/checkout", json={"plan_id": "plus_monthly"})
    assert resp.status_code == 503
    assert resp.json()["detail"] == "billing_unavailable"


async def test_checkout_returns_the_stripe_url(client, signed_in, monkeypatch):
    captured = {}

    async def _create(*, user_id, email, plan, customer_id):
        captured.update(user_id=user_id, email=email, plan=plan.id, customer_id=customer_id)
        return "https://checkout.stripe.com/c/pay/cs_test_123"

    monkeypatch.setattr(stripe_client, "is_configured", lambda: True)
    monkeypatch.setattr(stripe_client, "create_checkout_session", _create)

    resp = await client.post("/api/subscription/checkout", json={"plan_id": "plus_monthly"})

    assert resp.status_code == 200
    assert resp.json()["url"].startswith("https://checkout.stripe.com/")
    # The account is bound server-side, not taken from the request body.
    assert captured["user_id"] == signed_in
    assert captured["plan"] == "plus_monthly"


async def test_checkout_reuses_an_existing_stripe_customer(
    client, signed_in, db_sessionmaker, monkeypatch
):
    """A second purchase must not create a duplicate customer on Stripe."""
    async with db_sessionmaker() as s:
        s.add(Subscription(user_id=signed_in, stripe_customer_id="cus_existing"))
        await s.commit()

    captured = {}

    async def _create(*, user_id, email, plan, customer_id):
        captured["customer_id"] = customer_id
        return "https://checkout.stripe.com/c/pay/cs_test_123"

    monkeypatch.setattr(stripe_client, "is_configured", lambda: True)
    monkeypatch.setattr(stripe_client, "create_checkout_session", _create)

    await client.post("/api/subscription/checkout", json={"plan_id": "plus_monthly"})
    assert captured["customer_id"] == "cus_existing"


# ──────────────────────────────── portal ───────────────────────────────────


async def test_portal_requires_a_session(client):
    assert (await client.post("/api/subscription/portal", json={})).status_code == 401


async def test_portal_is_409_without_a_billing_account(client, signed_in, stripe_configured):
    resp = await client.post("/api/subscription/portal", json={})
    assert resp.status_code == 409
    assert resp.json()["detail"] == "no_billing_account"


async def test_portal_returns_a_url(client, signed_in, db_sessionmaker, monkeypatch):
    async with db_sessionmaker() as s:
        s.add(Subscription(user_id=signed_in, stripe_customer_id="cus_existing"))
        await s.commit()

    async def _portal(*, customer_id):
        assert customer_id == "cus_existing"
        return "https://billing.stripe.com/p/session/test_123"

    monkeypatch.setattr(stripe_client, "is_configured", lambda: True)
    monkeypatch.setattr(stripe_client, "create_portal_session", _portal)

    resp = await client.post("/api/subscription/portal", json={})
    assert resp.status_code == 200
    assert resp.json()["url"].startswith("https://billing.stripe.com/")


# ───────────────────────── client cannot self-promote ──────────────────────


async def test_a_client_supplied_plan_does_not_change_entitlement(
    client, signed_in, stripe_configured
):
    """The endpoint reads the database, never the request."""
    await client.post("/api/subscription/checkout", json={"plan_id": "plus_monthly"})
    body = (await client.get("/api/subscription")).json()
    assert body["plan_id"] == "free"
