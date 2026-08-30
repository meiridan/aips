"""The plan catalog.

Defined once server-side, the same way `maya.companions.catalog` holds the
wizard's options: the SPA renders whatever this returns and hardcodes no plan,
price or feature list. Stripe price ids come from the environment, so the same
code runs against test and live mode.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from maya.config import get_settings

FREE_PLAN_ID = "free"


@dataclass(frozen=True)
class Plan:
    id: str
    he: str
    description: str
    price: float
    currency: str
    # None for the free plan, which does not renew.
    interval: str | None
    features: list[str] = field(default_factory=list)
    # Which settings field holds this plan's Stripe price id.
    price_env: str | None = None

    def stripe_price_id(self) -> str | None:
        if self.price_env is None:
            return None
        return getattr(get_settings(), self.price_env, "") or None

    def as_dict(self) -> dict[str, Any]:
        """What the SPA gets. Deliberately omits the Stripe price id — the
        client picks a plan by our id, and the server maps it."""
        return {
            "id": self.id,
            "he": self.he,
            "description": self.description,
            "price": self.price,
            "currency": self.currency,
            "interval": self.interval,
            "features": list(self.features),
        }


_FREE_FEATURES = [
    "שיחה יומית מוגבלת",
    "יצירת דמות מלאה",
    "זיכרון בסיסי",
]
_PLUS_FEATURES = [
    "שיחות ללא הגבלה",
    "זיכרון ארוך טווח מלא",
    "תשובות ארוכות",
    "גישה גם בטלגרם",
]

PLANS: dict[str, Plan] = {
    FREE_PLAN_ID: Plan(
        id=FREE_PLAN_ID,
        he="חינם",
        description="להתחיל להכיר אותה.",
        price=0,
        currency="ILS",
        interval=None,
        features=_FREE_FEATURES,
    ),
    "plus_monthly": Plan(
        id="plus_monthly",
        he="פלוס",
        description="בלי הגבלות, בלי לספור הודעות.",
        price=39,
        currency="ILS",
        interval="month",
        features=_PLUS_FEATURES,
        price_env="stripe_price_plus_monthly",
    ),
    "plus_yearly": Plan(
        id="plus_yearly",
        he="פלוס שנתי",
        description="אותו דבר, בהנחה של חודשיים.",
        price=390,
        currency="ILS",
        interval="year",
        features=_PLUS_FEATURES,
        price_env="stripe_price_plus_yearly",
    ),
}

# Plans that grant the paid entitlement. The free plan is everything else.
PAID_PLAN_IDS = frozenset({"plus_monthly", "plus_yearly"})


def get(plan_id: str) -> Plan | None:
    return PLANS.get(plan_id)


def is_paid(plan_id: str) -> bool:
    return plan_id in PAID_PLAN_IDS


def as_list() -> list[dict[str, Any]]:
    """The catalog for ``GET /api/subscription/plans``."""
    return [plan.as_dict() for plan in PLANS.values()]


def by_stripe_price(price_id: str) -> Plan | None:
    """Map a Stripe price back to a plan, for the webhook."""
    for plan in PLANS.values():
        if plan.stripe_price_id() == price_id:
            return plan
    return None
