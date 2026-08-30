"""Stripe webhook handling.

This is the ONLY writer of the `subscriptions` table. Everything the app knows
about who has paid arrives here, signed by Stripe.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import stripe
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from maya.billing import plans
from maya.config import get_settings
from maya.db.models import StripeEvent, Subscription, User
from maya.logging import get_logger

log = get_logger("maya.billing")

# Everything else Stripe sends is ignored rather than guessed at.
HANDLED_EVENTS = frozenset(
    {
        "checkout.session.completed",
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "invoice.payment_failed",
    }
)


class InvalidSignature(RuntimeError):
    """The payload did not come from Stripe."""


def verify(payload: bytes, signature: str | None) -> dict[str, Any]:
    """Parse a webhook body, rejecting anything not signed by Stripe.

    Takes the RAW body: re-serializing parsed JSON changes the bytes and the
    signature stops matching.

    Uses the SDK only to check the signature — the one piece of this worth not
    hand-rolling — and then parses the body with `json.loads`. `construct_event`
    would return a `stripe.Event`, whose attribute access raises instead of
    returning None for absent fields, and whose dict conversion is a private
    method in v15. These payloads are full of fields that are legitimately
    absent depending on API version and event type, so a plain dict is both
    safer to read and not coupled to the SDK's object model.
    """
    secret = get_settings().stripe_webhook_secret
    # Fail closed. Treating "no secret" as "accept anything" would make the
    # subscriptions table writable by the whole internet.
    if not secret:
        raise InvalidSignature("STRIPE_WEBHOOK_SECRET is not set")
    try:
        # Checks the HMAC and the timestamp tolerance (Stripe's replay window).
        stripe.WebhookSignature.verify_header(
            payload.decode("utf-8"), signature or "", secret, tolerance=300
        )
        parsed = json.loads(payload)
    except Exception as exc:  # noqa: BLE001 - any failure here means "not Stripe"
        raise InvalidSignature(str(exc)) from None
    if not isinstance(parsed, dict):
        raise InvalidSignature("payload was not a JSON object")
    return parsed


async def _already_processed(sessionmaker: Any, event_id: str) -> bool:
    """Record the event id, returning whether it had been seen before.

    Stripe retries until it gets a 2xx, and delivery is at-least-once, so a
    replayed `subscription.updated` must not be applied twice.
    """
    async with sessionmaker() as session:
        result = await session.execute(
            insert(StripeEvent)
            .values(event_id=event_id)
            .on_conflict_do_nothing(index_elements=["event_id"])
        )
        await session.commit()
        return result.rowcount == 0


def _period_end(subscription: dict[str, Any]) -> datetime | None:
    raw = subscription.get("current_period_end")
    if not raw:
        # Newer API versions moved this onto the subscription's items.
        items = (subscription.get("items") or {}).get("data") or []
        raw = items[0].get("current_period_end") if items else None
    return datetime.fromtimestamp(int(raw), tz=UTC) if raw else None


def _plan_id(subscription: dict[str, Any]) -> str:
    """Prefer the price we actually sold; fall back to our own metadata."""
    items = (subscription.get("items") or {}).get("data") or []
    if items:
        price = (items[0].get("price") or {}).get("id")
        if price and (plan := plans.by_stripe_price(price)):
            return plan.id
    metadata = subscription.get("metadata") or {}
    candidate = metadata.get("plan_id")
    return candidate if candidate and plans.get(candidate) else plans.FREE_PLAN_ID


def _user_id_of(obj: dict[str, Any]) -> uuid.UUID | None:
    metadata = obj.get("metadata") or {}
    raw = metadata.get("user_id") or obj.get("client_reference_id")
    try:
        return uuid.UUID(str(raw)) if raw else None
    except ValueError:
        return None


async def _upsert(
    sessionmaker: Any,
    *,
    user_id: uuid.UUID | None,
    customer_id: str | None,
    subscription_id: str | None,
    plan_id: str,
    status: str,
    period_end: datetime | None,
    cancel_at_period_end: bool,
) -> None:
    async with sessionmaker() as session:
        row = None
        if user_id is not None:
            row = (
                await session.execute(select(Subscription).where(Subscription.user_id == user_id))
            ).scalar_one_or_none()
        if row is None and customer_id:
            # Later events in a subscription's life carry the customer but not
            # our metadata, so fall back to the customer we recorded at checkout.
            row = (
                await session.execute(
                    select(Subscription).where(Subscription.stripe_customer_id == customer_id)
                )
            ).scalar_one_or_none()
        if row is None:
            if user_id is None:
                log.warning("stripe_event_without_known_user", customer=customer_id)
                return
            # The id came from Stripe metadata, which can outlive the account
            # (deleted user, or an event replayed from another environment).
            # Inserting blind violates the foreign key, and a 500 here means
            # Stripe retries the same doomed event indefinitely.
            if await session.get(User, user_id) is None:
                log.warning("stripe_event_for_missing_user", user_id=str(user_id))
                return
            row = Subscription(user_id=user_id)
            session.add(row)

        row.plan_id = plan_id
        row.status = status
        row.current_period_end = period_end
        row.cancel_at_period_end = cancel_at_period_end
        if customer_id:
            row.stripe_customer_id = customer_id
        if subscription_id:
            row.stripe_subscription_id = subscription_id
        row.updated_at = datetime.now(UTC)
        await session.commit()


async def handle(sessionmaker: Any, event: dict[str, Any]) -> str:
    """Apply one verified event. Returns what was done, for logging/tests."""
    event_type = event.get("type", "")
    if event_type not in HANDLED_EVENTS:
        return "ignored"
    if await _already_processed(sessionmaker, event.get("id", "")):
        return "duplicate"

    obj = (event.get("data") or {}).get("object") or {}

    if event_type == "checkout.session.completed":
        # The session itself carries our metadata but not the period; the
        # subscription.created/updated event that follows fills that in.
        await _upsert(
            sessionmaker,
            user_id=_user_id_of(obj),
            customer_id=obj.get("customer"),
            subscription_id=obj.get("subscription"),
            plan_id=(obj.get("metadata") or {}).get("plan_id") or plans.FREE_PLAN_ID,
            status="active",
            period_end=None,
            cancel_at_period_end=False,
        )
        return "checkout_completed"

    if event_type == "invoice.payment_failed":
        await _upsert(
            sessionmaker,
            user_id=_user_id_of(obj),
            customer_id=obj.get("customer"),
            subscription_id=obj.get("subscription"),
            plan_id=plans.FREE_PLAN_ID,
            status="past_due",
            period_end=None,
            cancel_at_period_end=False,
        )
        return "payment_failed"

    # customer.subscription.created | updated | deleted
    deleted = event_type == "customer.subscription.deleted"
    await _upsert(
        sessionmaker,
        user_id=_user_id_of(obj),
        customer_id=obj.get("customer"),
        subscription_id=obj.get("id"),
        plan_id=plans.FREE_PLAN_ID if deleted else _plan_id(obj),
        status="canceled" if deleted else str(obj.get("status") or "incomplete"),
        period_end=None if deleted else _period_end(obj),
        cancel_at_period_end=bool(obj.get("cancel_at_period_end")),
    )
    return "subscription_updated"
