"""Stripe calls.

Uses the SDK's native async methods (`*_async`, available since v11) so nothing
blocks the event loop — the same reason the LLM and Telegram paths are async.
"""

from __future__ import annotations

import uuid
from typing import Any

import stripe

from maya.billing import plans
from maya.config import get_settings


class BillingNotConfigured(RuntimeError):
    """No Stripe key. The read-only screen still works; buying does not."""


def is_configured() -> bool:
    return bool(get_settings().stripe_secret_key)


def _client() -> Any:
    settings = get_settings()
    if not settings.stripe_secret_key:
        raise BillingNotConfigured("STRIPE_SECRET_KEY is not set")
    # A per-call client rather than the module-global `stripe.api_key`, so a
    # key rotation via settings takes effect without a restart.
    return stripe.StripeClient(settings.stripe_secret_key)


def _return_url(path: str) -> str:
    base = get_settings().public_base_url.rstrip("/") or "http://localhost:8000"
    return f"{base}{path}"


async def create_checkout_session(
    *,
    user_id: uuid.UUID,
    email: str | None,
    plan: plans.Plan,
    customer_id: str | None,
) -> str:
    """Return the hosted Checkout URL to send the browser to."""
    price_id = plan.stripe_price_id()
    if price_id is None:
        raise BillingNotConfigured(f"no Stripe price configured for plan {plan.id}")

    params: dict[str, Any] = {
        "mode": "subscription",
        "line_items": [{"price": price_id, "quantity": 1}],
        # Both are how the webhook ties Stripe's customer back to our account —
        # never trust a plan id the browser comes back with.
        "client_reference_id": str(user_id),
        "metadata": {"user_id": str(user_id), "plan_id": plan.id},
        "subscription_data": {"metadata": {"user_id": str(user_id), "plan_id": plan.id}},
        "success_url": _return_url("/subscription?checkout=success"),
        "cancel_url": _return_url("/subscription?checkout=cancelled"),
    }
    # Reuse the customer if we have one, so a second purchase doesn't create a
    # duplicate record on Stripe's side.
    if customer_id:
        params["customer"] = customer_id
    elif email:
        params["customer_email"] = email

    session = await _client().checkout.sessions.create_async(params=params)
    if not session.url:
        raise BillingNotConfigured("Stripe returned no checkout URL")
    return session.url


async def create_portal_session(*, customer_id: str) -> str:
    """Return the Billing Portal URL.

    Upgrade, downgrade and cancel all happen here rather than in endpoints of
    our own: it is one call instead of three, and proration and dunning stay
    Stripe's problem.
    """
    session = await _client().billing_portal.sessions.create_async(
        params={"customer": customer_id, "return_url": _return_url("/subscription")}
    )
    return session.url
