"""Subscription status, plan catalog, checkout, portal, and the Stripe webhook."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from maya.auth.deps import current_user
from maya.billing import entitlements, plans, stripe_client, webhook
from maya.db.models import User
from maya.db.session import get_sessionmaker
from maya.logging import get_logger

log = get_logger("maya.billing")

router = APIRouter(tags=["billing"])


class CheckoutRequest(BaseModel):
    plan_id: str


@router.get("/api/subscription/plans")
async def get_plans() -> dict:
    """The plan catalog. Public, so pricing can be shown before signing up."""
    return {"plans": plans.as_list()}


@router.get("/api/subscription")
async def get_subscription(user: User = Depends(current_user)) -> dict:
    """This account's entitlement, straight from the database."""
    return await entitlements.as_dict(get_sessionmaker(), user.id)


@router.post("/api/subscription/checkout")
async def checkout(payload: CheckoutRequest, user: User = Depends(current_user)) -> dict:
    """Start a Stripe Checkout session and hand back its URL.

    The client picks a plan by OUR id; the Stripe price is looked up here, so a
    tampered request can't buy something at the wrong price.
    """
    plan = plans.get(payload.plan_id)
    if plan is None or not plans.is_paid(plan.id):
        raise HTTPException(status_code=422, detail="unknown_plan")
    if not stripe_client.is_configured():
        raise HTTPException(status_code=503, detail="billing_unavailable")

    existing = await entitlements.get_subscription(get_sessionmaker(), user.id)
    try:
        url = await stripe_client.create_checkout_session(
            user_id=user.id,
            email=user.email,
            plan=plan,
            customer_id=existing.stripe_customer_id if existing else None,
        )
    except stripe_client.BillingNotConfigured as exc:
        log.warning("checkout_unavailable", error=str(exc))
        raise HTTPException(status_code=503, detail="billing_unavailable") from None
    return {"url": url}


@router.post("/api/subscription/portal")
async def portal(user: User = Depends(current_user)) -> dict:
    """Hand back a Stripe Billing Portal URL.

    Upgrade, downgrade and cancel all live there rather than in endpoints of
    our own.
    """
    if not stripe_client.is_configured():
        raise HTTPException(status_code=503, detail="billing_unavailable")

    existing = await entitlements.get_subscription(get_sessionmaker(), user.id)
    if existing is None or not existing.stripe_customer_id:
        raise HTTPException(status_code=409, detail="no_billing_account")

    try:
        url = await stripe_client.create_portal_session(customer_id=existing.stripe_customer_id)
    except stripe_client.BillingNotConfigured as exc:
        log.warning("portal_unavailable", error=str(exc))
        raise HTTPException(status_code=503, detail="billing_unavailable") from None
    return {"url": url}


@router.post("/billing/webhook")
async def stripe_webhook(request: Request) -> dict:
    """Inbound Stripe events — the only writer of the subscriptions table.

    Reads the RAW body: re-serializing parsed JSON would change the bytes and
    break the signature.
    """
    payload = await request.body()
    try:
        event = webhook.verify(payload, request.headers.get("stripe-signature"))
    except webhook.InvalidSignature as exc:
        log.warning("stripe_webhook_rejected", error=str(exc))
        raise HTTPException(status_code=400, detail="invalid_signature") from None

    outcome = await webhook.handle(get_sessionmaker(), event)
    log.info("stripe_webhook", type=event.get("type"), outcome=outcome)
    return {"ok": True}
