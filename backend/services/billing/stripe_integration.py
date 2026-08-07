"""
Stripe billing integration for ACX City.

Provides subscription management, metered usage tracking, invoicing,
and pricing tier logic on top of the Stripe API.

Environment variables:
    STRIPE_API_KEY          – Secret API key (required)
    STRIPE_WEBHOOK_SECRET   – Webhook signing secret (optional, for verification)
"""

from __future__ import annotations

import os
import time
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy Stripe import with graceful fallback
# ---------------------------------------------------------------------------
_stripe = None  # module-level cache


def _get_stripe():
    """Return the stripe module, importing it lazily on first call."""
    global _stripe
    if _stripe is None:
        try:
            import stripe as _mod
            _stripe = _mod
        except ImportError:
            raise ImportError(
                "The 'stripe' package is required for billing functionality. "
                "Install it with: pip install stripe"
            )
    return _stripe


# ---------------------------------------------------------------------------
# Pricing tiers
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PricingTier:
    """Represents a subscription pricing tier."""

    name: str
    price_id: str  # Stripe Price ID (empty string for free tier)
    monthly_price_cents: int
    included_units: int  # metered units included per month
    overage_rate_cents: int  # cost per additional unit (in cents)
    max_orgs: int  # -1 = unlimited
    features: tuple[str, ...] = ()


# Pre-defined tiers – replace price_ids with real Stripe Price IDs once created
TIER_FREE = PricingTier(
    name="free",
    price_id="",
    monthly_price_cents=0,
    included_units=1_000,
    overage_rate_cents=0,
    max_orgs=1,
    features=("basic_api", "community_support"),
)

TIER_STARTER = PricingTier(
    name="starter",
    price_id="price_starter_monthly",  # placeholder
    monthly_price_cents=2_900,  # $29.00
    included_units=50_000,
    overage_rate_cents=1,  # $0.01 / unit
    max_orgs=3,
    features=("basic_api", "email_support", "webhooks"),
)

TIER_PRO = PricingTier(
    name="pro",
    price_id="price_pro_monthly",  # placeholder
    monthly_price_cents=9_900,  # $99.00
    included_units=500_000,
    overage_rate_cents=0.5,  # $0.005 / unit
    max_orgs=10,
    features=(
        "basic_api",
        "priority_support",
        "webhooks",
        "advanced_analytics",
        "custom_branding",
    ),
)

TIER_ENTERPRISE = PricingTier(
    name="enterprise",
    price_id="price_enterprise_monthly",  # placeholder
    monthly_price_cents=49_900,  # $499.00
    included_units=5_000_000,
    overage_rate_cents=0.2,  # $0.002 / unit
    max_orgs=-1,
    features=(
        "basic_api",
        "dedicated_support",
        "webhooks",
        "advanced_analytics",
        "custom_branding",
        "sla_guarantee",
        "sso",
        "audit_logs",
    ),
)

TIERS: dict[str, PricingTier] = {
    t.name: t for t in [TIER_FREE, TIER_STARTER, TIER_PRO, TIER_ENTERPRISE]
}


# ---------------------------------------------------------------------------
# Billing calculation (offline, no Stripe call needed)
# ---------------------------------------------------------------------------
def calculate_bill(org_usage: dict[str, Any], tier: PricingTier) -> dict[str, Any]:
    """
    Calculate the bill for an organisation given its usage and pricing tier.

    Parameters
    ----------
    org_usage : dict
        Must contain ``total_units`` (int).  Optional keys:
        ``period_start`` / ``period_end`` (ISO-8601 strings).
    tier : PricingTier
        The pricing tier to apply.

    Returns
    -------
    dict
        Breakdown with keys: tier, included_units, total_units, overage_units,
        base_amount_cents, overage_amount_cents, total_amount_cents,
        total_amount_display, period_start, period_end.
    """
    total_units = int(org_usage.get("total_units", 0))
    included = tier.included_units
    overage = max(0, total_units - included)

    base = tier.monthly_price_cents
    overage_cost = int(overage * tier.overage_rate_cents)
    total = base + overage_cost

    return {
        "tier": tier.name,
        "included_units": included,
        "total_units": total_units,
        "overage_units": overage,
        "base_amount_cents": base,
        "overage_amount_cents": overage_cost,
        "total_amount_cents": total,
        "total_amount_display": f"${total / 100:,.2f}",
        "period_start": org_usage.get("period_start"),
        "period_end": org_usage.get("period_end"),
    }


# ---------------------------------------------------------------------------
# Stripe billing service
# ---------------------------------------------------------------------------
class StripeBilling:
    """
    High-level wrapper around Stripe for ACX City billing operations.

    All methods return plain dicts so callers never depend on the Stripe SDK
    directly.  The Stripe module is imported lazily so the rest of the
    application can start without it installed.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.environ.get("STRIPE_API_KEY", "")
        self._webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
        if not self._api_key:
            logger.warning(
                "STRIPE_API_KEY is not set – Stripe calls will fail at runtime."
            )

    # -- helpers ----------------------------------------------------------

    def _configure(self) -> None:
        """Push the API key into the stripe module before each call."""
        stripe = _get_stripe()
        stripe.api_key = self._api_key
        return stripe

    @staticmethod
    def _to_dict(obj: Any) -> dict[str, Any]:
        """Convert a Stripe object (or raw dict) to a plain dict."""
        if isinstance(obj, dict):
            return obj
        # Stripe objects expose .to_dict_recursive() in newer SDKs
        if hasattr(obj, "to_dict_recursive"):
            return obj.to_dict_recursive()
        # Fallback: __dict__ + strip private keys
        return {k: v for k, v in getattr(obj, "__dict__", {}).items() if not k.startswith("_")}

    # -- public API -------------------------------------------------------

    def create_customer(
        self,
        org_id: str,
        email: str,
        name: str,
    ) -> dict[str, Any]:
        """
        Create a Stripe Customer linked to an ACX City organisation.

        Returns the customer object as a dict (includes ``id``).
        """
        stripe = self._configure()
        customer = stripe.Customer.create(
            email=email,
            name=name,
            metadata={"org_id": org_id, "platform": "acx-city"},
        )
        logger.info("Created Stripe customer %s for org %s", customer.id, org_id)
        return self._to_dict(customer)

    def create_subscription(
        self,
        customer_id: str,
        price_id: str,
    ) -> dict[str, Any]:
        """
        Create a subscription for *customer_id* at the given *price_id*.

        Supports both flat-rate and metered pricing.  Returns the
        subscription object as a dict.
        """
        stripe = self._configure()
        subscription = stripe.Subscription.create(
            customer=customer_id,
            items=[{"price": price_id}],
            payment_behavior="default_incomplete",
            expand=["latest_invoice.payment_intent"],
        )
        logger.info(
            "Created subscription %s for customer %s (price %s)",
            subscription.id,
            customer_id,
            price_id,
        )
        return self._to_dict(subscription)

    def record_usage(
        self,
        customer_id: str,
        quantity: int,
        timestamp: int | float | None = None,
    ) -> dict[str, Any]:
        """
        Record metered usage for a customer.

        Parameters
        ----------
        customer_id : str
            Stripe customer ID.
        quantity : int
            Number of units consumed.
        timestamp : int | float | None
            Unix epoch timestamp.  Defaults to ``time.time()``.

        Returns
        -------
        dict
            The usage record object.
        """
        stripe = self._configure()
        ts = int(timestamp or time.time())

        # Find the active subscription's metered item
        subs = stripe.Subscription.list(customer=customer_id, status="active", limit=1)
        if not subs.data:
            raise ValueError(f"No active subscription found for customer {customer_id}")

        sub = subs.data[0]
        metered_items = [i for i in sub["items"]["data"] if i.price.recurring.usage_type == "metered"]
        if not metered_items:
            raise ValueError(
                f"Subscription {sub.id} has no metered billing items"
            )

        subscription_item_id = metered_items[0].id
        usage_record = stripe.SubscriptionItem.create_usage_record(
            subscription_item_id,
            quantity=quantity,
            timestamp=ts,
            action="increment",
        )
        logger.info(
            "Recorded %d usage units for customer %s (item %s)",
            quantity,
            customer_id,
            subscription_item_id,
        )
        return self._to_dict(usage_record)

    def create_invoice(self, customer_id: str) -> dict[str, Any]:
        """
        Create (and finalise) an invoice for the given customer.

        Returns the invoice object as a dict.
        """
        stripe = self._configure()
        invoice = stripe.Invoice.create(customer=customer_id)
        invoice = stripe.Invoice.finalize_invoice(invoice.id)
        logger.info("Created & finalised invoice %s for %s", invoice.id, customer_id)
        return self._to_dict(invoice)

    def get_usage_summary(
        self,
        customer_id: str,
        period_start: int | float,
        period_end: int | float,
    ) -> dict[str, Any]:
        """
        Retrieve a usage summary for a customer over a billing period.

        Parameters
        ----------
        customer_id : str
            Stripe customer ID.
        period_start, period_end : int | float
            Unix epoch timestamps bounding the period.

        Returns
        -------
        dict
            Keys: customer_id, period_start, period_end, total_usage,
            line_items (list of per-item breakdowns).
        """
        stripe = self._configure()

        subs = stripe.Subscription.list(customer=customer_id, status="active", limit=1)
        if not subs.data:
            return {
                "customer_id": customer_id,
                "period_start": period_start,
                "period_end": period_end,
                "total_usage": 0,
                "line_items": [],
            }

        sub = subs.data[0]
        line_items: list[dict[str, Any]] = []
        total = 0

        for item in sub["items"]["data"]:
            if item.price.recurring.usage_type != "metered":
                continue
            records = stripe.SubscriptionItem.list_usage_record_summaries(
                item.id,
                limit=100,
            )
            item_total = sum(r.total_usage for r in records.data)
            total += item_total
            line_items.append({
                "subscription_item_id": item.id,
                "price_id": item.price.id,
                "usage": item_total,
            })

        return {
            "customer_id": customer_id,
            "period_start": period_start,
            "period_end": period_end,
            "total_usage": total,
            "line_items": line_items,
        }

    def create_checkout_session(
        self,
        customer_id: str,
        price_id: str,
        success_url: str,
        cancel_url: str,
    ) -> dict[str, Any]:
        """
        Create a Stripe Checkout Session for a new subscription.

        Parameters
        ----------
        customer_id : str
            Stripe customer ID.
        price_id : str
            Stripe Price ID to subscribe to.
        success_url : str
            Redirect URL on successful payment.
        cancel_url : str
            Redirect URL if the customer cancels.

        Returns
        -------
        dict
            Checkout session object (includes ``url`` for redirect).
        """
        stripe = self._configure()
        session = stripe.checkout.Session.create(
            customer=customer_id,
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
        )
        logger.info("Created checkout session %s for %s", session.id, customer_id)
        return self._to_dict(session)

    def verify_webhook(self, payload: bytes, sig_header: str) -> dict[str, Any]:
        """
        Verify a Stripe webhook signature and return the event.

        Raises ``stripe.error.SignatureVerificationError`` on failure.

        Parameters
        ----------
        payload : bytes
            Raw request body.
        sig_header : str
            The ``Stripe-Signature`` header value.

        Returns
        -------
        dict
            The verified Stripe event object.
        """
        stripe = self._configure()
        if not self._webhook_secret:
            raise ValueError("STRIPE_WEBHOOK_SECRET is not configured")
        event = stripe.Webhook.construct_event(payload, sig_header, self._webhook_secret)
        return self._to_dict(event)
