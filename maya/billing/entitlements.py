"""What an account is actually entitled to.

The single source of truth for "is this user a subscriber". Nothing here reads
anything the client sent: the answer comes from the `subscriptions` row, which
only the Stripe webhook writes. A user cannot talk themselves into a plan by
posting a plan id.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, TypeGuard

from sqlalchemy import func, select

from maya.billing import plans
from maya.config import get_settings
from maya.db.models import Message, Subscription

# Stripe statuses that mean the customer has paid and should be served.
# `past_due` is deliberately excluded: Stripe keeps retrying, and until it
# succeeds the entitlement is not there.
ACTIVE_STATUSES = frozenset({"active", "trialing"})


async def get_subscription(sessionmaker: Any, user_id: uuid.UUID) -> Subscription | None:
    async with sessionmaker() as session:
        return (
            await session.execute(select(Subscription).where(Subscription.user_id == user_id))
        ).scalar_one_or_none()


def _is_live(row: Subscription | None) -> TypeGuard[Subscription]:
    """True when this row grants the paid entitlement right now.

    A TypeGuard so callers can read `row.plan_id` afterwards without a second
    None check.
    """
    if row is None or row.status not in ACTIVE_STATUSES:
        return False
    # A row can sit at "active" if a webhook was missed; the period end is the
    # backstop so a lapsed subscription cannot linger indefinitely.
    if row.current_period_end is not None and row.current_period_end <= datetime.now(UTC):
        return False
    return plans.is_paid(row.plan_id)


async def active_plan_id(sessionmaker: Any, user_id: uuid.UUID) -> str:
    """The plan this user is entitled to right now."""
    row = await get_subscription(sessionmaker, user_id)
    return row.plan_id if _is_live(row) else plans.FREE_PLAN_ID


async def is_subscriber(sessionmaker: Any, user_id: uuid.UUID) -> bool:
    return plans.is_paid(await active_plan_id(sessionmaker, user_id))


async def messages_sent_today(sessionmaker: Any, user_id: uuid.UUID) -> int:
    since = datetime.now(UTC) - timedelta(days=1)
    async with sessionmaker() as session:
        return (
            await session.execute(
                select(func.count())
                .select_from(Message)
                .where(Message.user_id == user_id)
                .where(Message.role == "user")
                .where(Message.created_at >= since)
            )
        ).scalar_one()


async def quota_exceeded(sessionmaker: Any, user_id: uuid.UUID) -> bool:
    """Whether a free account has used up its daily allowance.

    Checked on the server before every turn, on both channels. The client is
    never asked and never trusted — hiding the compose box would be a hint, not
    a limit.
    """
    limit = get_settings().free_daily_message_limit
    if limit <= 0:  # 0 or negative disables the cap entirely.
        return False
    if await is_subscriber(sessionmaker, user_id):
        return False
    return await messages_sent_today(sessionmaker, user_id) >= limit


async def as_dict(sessionmaker: Any, user_id: uuid.UUID) -> dict[str, Any]:
    """The shape `GET /api/subscription` returns."""
    row = await get_subscription(sessionmaker, user_id)
    return {
        "plan_id": row.plan_id if _is_live(row) else plans.FREE_PLAN_ID,
        "status": row.status if row is not None else "inactive",
        "current_period_end": (
            row.current_period_end.isoformat()
            if row is not None and row.current_period_end
            else None
        ),
        "cancel_at_period_end": bool(row.cancel_at_period_end) if row is not None else False,
        # Whether there is anything for the Stripe portal to manage.
        "manageable": bool(row is not None and row.stripe_customer_id),
    }
