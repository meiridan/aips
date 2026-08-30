"""The Stripe webhook — the only writer of the subscriptions table."""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import pytest_asyncio
import stripe
from sqlalchemy import select

import maya.api.billing as billing_api
import maya.web as web
from maya.billing import webhook
from maya.db.models import StripeEvent, Subscription
from tests.conftest import db_required

pytestmark = db_required

SECRET = "whsec_test_secret"


@pytest.fixture(autouse=True)
def _webhook_secret(monkeypatch):
    from maya.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("STRIPE_PRICE_PLUS_MONTHLY", "price_monthly_test")
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def client(db_sessionmaker, monkeypatch):
    monkeypatch.setattr(billing_api, "get_sessionmaker", lambda: db_sessionmaker)
    transport = httpx.ASGITransport(app=web.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def signed(event: dict) -> tuple[bytes, str]:
    """Sign a payload the way Stripe does, so `construct_event` accepts it."""
    payload = json.dumps(event).encode()
    timestamp = int(time.time())
    signature = stripe.WebhookSignature._compute_signature(
        f"{timestamp}.{payload.decode()}", SECRET
    )
    return payload, f"t={timestamp},v1={signature}"


async def post(client, event: dict):
    payload, signature = signed(event)
    return await client.post(
        "/billing/webhook", content=payload, headers={"stripe-signature": signature}
    )


def subscription_event(
    user_id,
    *,
    event_id="evt_1",
    event_type="customer.subscription.updated",
    status="active",
    cancel=False,
    price="price_monthly_test",
):
    return {
        "id": event_id,
        "type": event_type,
        "data": {
            "object": {
                "id": "sub_123",
                "customer": "cus_123",
                "status": status,
                "cancel_at_period_end": cancel,
                "metadata": {"user_id": str(user_id)},
                "items": {
                    "data": [
                        {
                            "price": {"id": price},
                            "current_period_end": int(
                                (datetime.now(UTC) + timedelta(days=30)).timestamp()
                            ),
                        }
                    ]
                },
            }
        },
    }


async def _row(sm, user_id):
    async with sm() as s:
        return (
            await s.execute(select(Subscription).where(Subscription.user_id == user_id))
        ).scalar_one_or_none()


# ──────────────────────────── signature check ──────────────────────────────


async def test_an_unsigned_payload_is_rejected(client, seeded_ids):
    user_id, _ = seeded_ids
    resp = await client.post("/billing/webhook", json=subscription_event(user_id))
    assert resp.status_code == 400
    assert resp.json()["detail"] == "invalid_signature"


async def test_a_forged_signature_is_rejected(client, seeded_ids, db_sessionmaker):
    user_id, _ = seeded_ids
    payload = json.dumps(subscription_event(user_id)).encode()
    resp = await client.post(
        "/billing/webhook",
        content=payload,
        headers={"stripe-signature": f"t={int(time.time())},v1=deadbeef"},
    )
    assert resp.status_code == 400
    assert await _row(db_sessionmaker, user_id) is None


async def test_a_stale_timestamp_is_rejected(client, seeded_ids):
    """Replay protection: Stripe's tolerance window."""
    user_id, _ = seeded_ids
    payload = json.dumps(subscription_event(user_id)).encode()
    old = int(time.time()) - 3600
    signature = stripe.WebhookSignature._compute_signature(f"{old}.{payload.decode()}", SECRET)
    resp = await client.post(
        "/billing/webhook",
        content=payload,
        headers={"stripe-signature": f"t={old},v1={signature}"},
    )
    assert resp.status_code == 400


# ───────────────────────────── applying events ─────────────────────────────


async def test_subscription_updated_upserts_the_row(client, seeded_ids, db_sessionmaker):
    user_id, _ = seeded_ids
    assert (await post(client, subscription_event(user_id))).status_code == 200

    row = await _row(db_sessionmaker, user_id)
    assert row is not None
    assert row.plan_id == "plus_monthly"
    assert row.status == "active"
    assert row.stripe_customer_id == "cus_123"
    assert row.stripe_subscription_id == "sub_123"
    assert row.current_period_end is not None


async def test_the_plan_comes_from_the_price_not_the_client(client, seeded_ids, db_sessionmaker):
    """Stripe tells us what was actually bought."""
    user_id, _ = seeded_ids
    event = subscription_event(user_id)
    event["data"]["object"]["metadata"]["plan_id"] = "plus_yearly"  # a lie
    await post(client, event)
    assert (await _row(db_sessionmaker, user_id)).plan_id == "plus_monthly"


async def test_deletion_drops_the_account_to_free(client, seeded_ids, db_sessionmaker):
    user_id, _ = seeded_ids
    await post(client, subscription_event(user_id))
    await post(
        client,
        subscription_event(user_id, event_id="evt_2", event_type="customer.subscription.deleted"),
    )
    row = await _row(db_sessionmaker, user_id)
    assert row.plan_id == "free"
    assert row.status == "canceled"


async def test_payment_failure_marks_past_due(client, seeded_ids, db_sessionmaker):
    user_id, _ = seeded_ids
    await post(client, subscription_event(user_id))
    await post(
        client,
        {
            "id": "evt_fail",
            "type": "invoice.payment_failed",
            "data": {
                "object": {
                    "customer": "cus_123",
                    "subscription": "sub_123",
                    "metadata": {"user_id": str(user_id)},
                }
            },
        },
    )
    assert (await _row(db_sessionmaker, user_id)).status == "past_due"


async def test_cancel_at_period_end_is_recorded(client, seeded_ids, db_sessionmaker):
    user_id, _ = seeded_ids
    await post(client, subscription_event(user_id, cancel=True))
    assert (await _row(db_sessionmaker, user_id)).cancel_at_period_end is True


async def test_checkout_completed_binds_the_customer(client, seeded_ids, db_sessionmaker):
    user_id, _ = seeded_ids
    await post(
        client,
        {
            "id": "evt_checkout",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "customer": "cus_new",
                    "subscription": "sub_new",
                    "client_reference_id": str(user_id),
                    "metadata": {"user_id": str(user_id), "plan_id": "plus_monthly"},
                }
            },
        },
    )
    row = await _row(db_sessionmaker, user_id)
    assert row.stripe_customer_id == "cus_new"
    assert row.plan_id == "plus_monthly"


async def test_a_later_event_matches_by_customer_alone(client, seeded_ids, db_sessionmaker):
    """Events after checkout carry the customer but not our metadata."""
    user_id, _ = seeded_ids
    await post(client, subscription_event(user_id))

    event = subscription_event(user_id, event_id="evt_no_meta")
    event["data"]["object"]["metadata"] = {}
    await post(client, event)

    async with db_sessionmaker() as s:
        assert len((await s.scalars(select(Subscription))).all()) == 1


# ───────────────────────────── idempotency ─────────────────────────────────


async def test_a_replayed_event_is_a_noop(client, seeded_ids, db_sessionmaker):
    """Stripe delivers at least once; applying twice must be harmless."""
    user_id, _ = seeded_ids
    event = subscription_event(user_id)
    assert (await post(client, event)).status_code == 200
    assert (await post(client, event)).status_code == 200

    async with db_sessionmaker() as s:
        assert len((await s.scalars(select(StripeEvent))).all()) == 1
        assert len((await s.scalars(select(Subscription))).all()) == 1


async def test_a_replay_cannot_resurrect_a_cancellation(client, seeded_ids, db_sessionmaker):
    """The ordering hazard: re-delivering the old 'active' event after a cancel
    must not put the account back on a paid plan."""
    user_id, _ = seeded_ids
    active = subscription_event(user_id, event_id="evt_active")
    await post(client, active)
    await post(
        client,
        subscription_event(
            user_id, event_id="evt_deleted", event_type="customer.subscription.deleted"
        ),
    )
    await post(client, active)  # replayed

    row = await _row(db_sessionmaker, user_id)
    assert row.plan_id == "free"
    assert row.status == "canceled"


async def test_an_unhandled_event_type_is_ignored(client, seeded_ids, db_sessionmaker):
    user_id, _ = seeded_ids
    resp = await post(
        client, {"id": "evt_other", "type": "customer.created", "data": {"object": {}}}
    )
    assert resp.status_code == 200
    assert await _row(db_sessionmaker, user_id) is None


async def test_an_event_for_an_unknown_user_is_dropped(client, db_sessionmaker):
    """No account to attach it to, and nothing should be invented."""
    resp = await post(client, subscription_event(uuid.uuid4(), event_id="evt_ghost"))
    assert resp.status_code == 200
    async with db_sessionmaker() as s:
        assert (await s.scalars(select(Subscription))).all() == []


def test_verify_refuses_when_no_secret_is_configured(monkeypatch):
    """Fail closed: an unconfigured secret must not mean 'accept everything'."""
    from maya.config import get_settings

    get_settings.cache_clear()
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    try:
        with pytest.raises(webhook.InvalidSignature):
            webhook.verify(b"{}", "t=1,v1=x")
    finally:
        get_settings.cache_clear()
