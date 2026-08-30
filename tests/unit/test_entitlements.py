"""Entitlement is decided server-side, from the subscriptions row only."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from maya.billing import entitlements, plans
from maya.db.models import Message, Subscription
from tests.conftest import db_required

pytestmark = db_required


async def _subscribe(sm, user_id, **overrides):
    values = {
        "plan_id": "plus_monthly",
        "status": "active",
        "current_period_end": datetime.now(UTC) + timedelta(days=20),
        "stripe_customer_id": "cus_test",
    }
    values.update(overrides)
    async with sm() as session:
        session.add(Subscription(user_id=user_id, **values))
        await session.commit()


async def test_no_row_means_the_free_plan(db_sessionmaker, seeded_ids):
    user_id, _ = seeded_ids
    assert await entitlements.active_plan_id(db_sessionmaker, user_id) == plans.FREE_PLAN_ID
    assert await entitlements.is_subscriber(db_sessionmaker, user_id) is False


async def test_an_active_subscription_grants_the_plan(db_sessionmaker, seeded_ids):
    user_id, _ = seeded_ids
    await _subscribe(db_sessionmaker, user_id)
    assert await entitlements.active_plan_id(db_sessionmaker, user_id) == "plus_monthly"
    assert await entitlements.is_subscriber(db_sessionmaker, user_id) is True


async def test_an_expired_period_does_not_count(db_sessionmaker, seeded_ids):
    """The backstop for a webhook we never received."""
    user_id, _ = seeded_ids
    await _subscribe(
        db_sessionmaker, user_id, current_period_end=datetime.now(UTC) - timedelta(minutes=1)
    )
    assert await entitlements.is_subscriber(db_sessionmaker, user_id) is False


@pytest.mark.parametrize("status", ["past_due", "canceled", "incomplete", "unpaid", "paused"])
async def test_only_active_and_trialing_count(db_sessionmaker, seeded_ids, status):
    user_id, _ = seeded_ids
    await _subscribe(db_sessionmaker, user_id, status=status)
    assert await entitlements.is_subscriber(db_sessionmaker, user_id) is False


async def test_trialing_counts(db_sessionmaker, seeded_ids):
    user_id, _ = seeded_ids
    await _subscribe(db_sessionmaker, user_id, status="trialing")
    assert await entitlements.is_subscriber(db_sessionmaker, user_id) is True


async def test_an_unknown_plan_id_is_not_a_paid_plan(db_sessionmaker, seeded_ids):
    """A row that somehow names a plan we don't sell must not grant anything."""
    user_id, _ = seeded_ids
    await _subscribe(db_sessionmaker, user_id, plan_id="platinum_unlimited")
    assert await entitlements.is_subscriber(db_sessionmaker, user_id) is False


# ─────────────────────────────── the quota ─────────────────────────────────


async def _send(sm, user_id, companion_id, count, *, age=timedelta(0)):
    async with sm() as session:
        for i in range(count):
            session.add(
                Message(
                    companion_id=companion_id,
                    user_id=user_id,
                    role="user",
                    content=f"m{i}",
                    created_at=datetime.now(UTC) - age,
                )
            )
        await session.commit()


async def test_free_account_under_the_cap_may_send(db_sessionmaker, seeded_ids, monkeypatch):
    from maya.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("FREE_DAILY_MESSAGE_LIMIT", "5")
    try:
        user_id, companion_id = seeded_ids
        await _send(db_sessionmaker, user_id, companion_id, 4)
        assert await entitlements.quota_exceeded(db_sessionmaker, user_id) is False
    finally:
        get_settings.cache_clear()


async def test_free_account_at_the_cap_is_blocked(db_sessionmaker, seeded_ids, monkeypatch):
    from maya.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("FREE_DAILY_MESSAGE_LIMIT", "5")
    try:
        user_id, companion_id = seeded_ids
        await _send(db_sessionmaker, user_id, companion_id, 5)
        assert await entitlements.quota_exceeded(db_sessionmaker, user_id) is True
    finally:
        get_settings.cache_clear()


async def test_a_subscriber_is_never_blocked(db_sessionmaker, seeded_ids, monkeypatch):
    from maya.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("FREE_DAILY_MESSAGE_LIMIT", "5")
    try:
        user_id, companion_id = seeded_ids
        await _subscribe(db_sessionmaker, user_id)
        await _send(db_sessionmaker, user_id, companion_id, 50)
        assert await entitlements.quota_exceeded(db_sessionmaker, user_id) is False
    finally:
        get_settings.cache_clear()


async def test_yesterdays_messages_do_not_count(db_sessionmaker, seeded_ids, monkeypatch):
    from maya.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("FREE_DAILY_MESSAGE_LIMIT", "5")
    try:
        user_id, companion_id = seeded_ids
        await _send(db_sessionmaker, user_id, companion_id, 20, age=timedelta(days=2))
        assert await entitlements.quota_exceeded(db_sessionmaker, user_id) is False
    finally:
        get_settings.cache_clear()


async def test_assistant_replies_do_not_count_against_the_user(
    db_sessionmaker, seeded_ids, monkeypatch
):
    from maya.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("FREE_DAILY_MESSAGE_LIMIT", "5")
    try:
        user_id, companion_id = seeded_ids
        async with db_sessionmaker() as session:
            for i in range(20):
                session.add(
                    Message(
                        companion_id=companion_id,
                        user_id=user_id,
                        role="assistant",
                        content=f"r{i}",
                    )
                )
            await session.commit()
        assert await entitlements.quota_exceeded(db_sessionmaker, user_id) is False
    finally:
        get_settings.cache_clear()


async def test_a_zero_limit_disables_the_cap(db_sessionmaker, seeded_ids, monkeypatch):
    from maya.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("FREE_DAILY_MESSAGE_LIMIT", "0")
    try:
        user_id, companion_id = seeded_ids
        await _send(db_sessionmaker, user_id, companion_id, 100)
        assert await entitlements.quota_exceeded(db_sessionmaker, user_id) is False
    finally:
        get_settings.cache_clear()


async def test_quota_is_counted_per_account(db_sessionmaker, seeded_ids, monkeypatch):
    """One heavy user must not exhaust anyone else's allowance."""
    from maya.config import get_settings
    from maya.db.models import User

    get_settings.cache_clear()
    monkeypatch.setenv("FREE_DAILY_MESSAGE_LIMIT", "5")
    try:
        heavy, companion_id = seeded_ids
        await _send(db_sessionmaker, heavy, companion_id, 10)
        async with db_sessionmaker() as session:
            other = User(name="Bystander")
            session.add(other)
            await session.commit()
            quiet = other.id
        assert await entitlements.quota_exceeded(db_sessionmaker, heavy) is True
        assert await entitlements.quota_exceeded(db_sessionmaker, quiet) is False
    finally:
        get_settings.cache_clear()
