# mvp/api/routers/payments.py
"""Stripe Payment & Subscription endpoints."""
from __future__ import annotations

import os
import uuid as uuid_mod
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import text

from ..db import SessionLocal
from ..schemas import SubscriptionResponse
from ..auth import get_current_user_jwt
from ...common.plan_limits import PLAN_LIMITS, count_links_for_tenant, get_tenant_plan
from ...common.repositories import get_tenant_subscription

router = APIRouter(prefix="/payments", tags=["payments"])
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Stripe config (loaded lazily so import doesn't crash if not set)
# ------------------------------------------------------------------
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICING_TABLE_ID = os.getenv("STRIPE_PRICING_TABLE_ID", "")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
PLAN_CODES = {"pro", "pro_plus"}


def _stripe_imported():
    try:
        import stripe
        return stripe
    except ImportError:
        raise HTTPException(status_code=500, detail="Stripe library not installed")


def _obj_get(obj, key: str, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _normalize_plan_code(value: str | None) -> str | None:
    if not value:
        return None
    normalized = str(value).strip().lower().replace(" ", "_")
    if normalized in PLAN_CODES:
        return normalized
    if normalized in {"proplus", "pro-plus", "pro_plus"}:
        return "pro_plus"
    if normalized == "pro":
        return "pro"
    return None


def _plan_from_price_object(price_obj) -> str | None:
    if not price_obj:
        return None

    metadata = _obj_get(price_obj, "metadata", {}) or {}
    if isinstance(metadata, dict):
        for key in ("plan_code", "plan", "tier"):
            plan = _normalize_plan_code(metadata.get(key))
            if plan:
                return plan

    lookup_key = _normalize_plan_code(_obj_get(price_obj, "lookup_key"))
    if lookup_key:
        return lookup_key

    nickname = str(_obj_get(price_obj, "nickname", "")).lower()
    if "pro+" in nickname or "pro plus" in nickname:
        return "pro_plus"
    if nickname == "pro":
        return "pro"

    product = _obj_get(price_obj, "product")
    if isinstance(product, dict):
        product_meta = product.get("metadata") or {}
        if isinstance(product_meta, dict):
            for key in ("plan_code", "plan", "tier"):
                plan = _normalize_plan_code(product_meta.get(key))
                if plan:
                    return plan
        product_name = str(product.get("name", "")).lower()
        if "pro+" in product_name or "pro plus" in product_name:
            return "pro_plus"
        if product_name == "pro":
            return "pro"

    return None


def _plan_from_subscription(subscription) -> str | None:
    items = _obj_get(subscription, "items", {})
    data = _obj_get(items, "data", []) or []
    for item in data:
        plan = _plan_from_price_object(_obj_get(item, "price"))
        if plan:
            return plan
    return None


def _activate_subscription(session: Session, tenant_id: str, customer_id: str | None, subscription_id: str, plan: str) -> None:
    if plan not in PLAN_CODES:
        logger.warning("Skipping subscription activation because plan could not be determined tenant_id=%s subscription_id=%s", tenant_id, subscription_id)
        return

    _upsert_subscription(
        session,
        tenant_id=tenant_id,
        stripe_customer_id=customer_id,
        stripe_subscription_id=subscription_id,
        plan=plan,
        status="active",
    )
    session.execute(
        text("UPDATE tenants SET plan = :plan WHERE id = :id"),
        {"plan": plan, "id": tenant_id},
    )
    session.commit()


@router.get("/plans")
def list_plans():
    """Return billing plan availability for the dashboard."""
    billing_ready = bool(STRIPE_PRICING_TABLE_ID and STRIPE_PUBLISHABLE_KEY)
    plans = [
        {"name": "free", "label": "Free", "enabled": True},
        {"name": "pro", "label": "Pro", "enabled": billing_ready},
        {"name": "pro_plus", "label": "Pro+", "enabled": billing_ready},
    ]
    return {
        "enabled": billing_ready,
        "pricing_table_id": STRIPE_PRICING_TABLE_ID or None,
        "publishable_key": STRIPE_PUBLISHABLE_KEY or None,
        "plans": plans,
    }


@router.get("/pricing-table")
def get_pricing_table_config():
    return list_plans()


def get_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ------------------------------------------------------------------
# Checkout
# ------------------------------------------------------------------
@router.post("/checkout")
def create_checkout(
    plan: str = "pro",
    current_user: dict = Depends(get_current_user_jwt),
    session: Session = Depends(get_session),
):
    raise HTTPException(status_code=410, detail="Use Stripe pricing table instead")


# ------------------------------------------------------------------
# Webhook
# ------------------------------------------------------------------
@router.post("/webhook")
async def stripe_webhook(request: Request, session: Session = Depends(get_session)):
    """Handle Stripe webhook events for subscription lifecycle."""
    if not STRIPE_SECRET_KEY or not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Stripe not configured")

    stripe = _stripe_imported()
    stripe.api_key = STRIPE_SECRET_KEY

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Webhook verification failed: {exc}")

    event_type = event.get("type")
    data = event.get("data", {}).get("object", {})

    if event_type in ("checkout.session.completed", "invoice.paid"):
        customer_id = data.get("customer")
        subscription_id = data.get("subscription")
        client_ref = data.get("client_reference_id")
        tenant_id = client_ref or _resolve_tenant_by_customer(session, customer_id)

        if tenant_id and subscription_id:
            subscription = stripe.Subscription.retrieve(
                subscription_id,
                expand=["items.data.price", "items.data.price.product"],
            )
            plan = _plan_from_subscription(subscription)
            _activate_subscription(
                session,
                tenant_id=tenant_id,
                customer_id=customer_id,
                subscription_id=subscription_id,
                plan=plan or "free",
            )

    elif event_type in ("customer.subscription.deleted", "customer.subscription.updated"):
        subscription_id = data.get("id")
        status = data.get("status")
        row = session.execute(
            text("SELECT tenant_id FROM subscriptions WHERE stripe_subscription_id = :sid"),
            {"sid": subscription_id},
        ).fetchone()
        if row:
            tenant_id = row[0]
            new_plan = "free"
            new_sub_status = "active" if status in ("active", "trialing") else "cancelled"
            if status in ("active", "trialing"):
                subscription = stripe.Subscription.retrieve(
                    subscription_id,
                    expand=["items.data.price", "items.data.price.product"],
                )
                derived_plan = _plan_from_subscription(subscription)
                if not derived_plan:
                    logger.warning(
                        "Skipping subscription update because plan could not be determined tenant_id=%s subscription_id=%s",
                        tenant_id,
                        subscription_id,
                    )
                    return {"status": "ok"}
                new_plan = derived_plan
            _upsert_subscription(
                session,
                tenant_id=tenant_id,
                stripe_subscription_id=subscription_id,
                plan=new_plan,
                status=new_sub_status,
            )
            session.execute(
                text("UPDATE tenants SET plan = :plan WHERE id = :id"),
                {"plan": new_plan, "id": tenant_id},
            )
            session.commit()

    return {"status": "ok"}


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def _resolve_tenant_by_customer(session: Session, customer_id: str) -> str | None:
    row = session.execute(
        text("SELECT tenant_id FROM subscriptions WHERE stripe_customer_id = :cid"),
        {"cid": customer_id},
    ).fetchone()
    return row[0] if row else None


def _upsert_subscription(
    session: Session,
    tenant_id: str,
    stripe_customer_id: str = None,
    stripe_subscription_id: str = None,
    plan: str = "free",
    status: str = "active",
):
    sub_id = uuid_mod.uuid4()
    session.execute(
        text(
            """
            INSERT INTO subscriptions (
                id, tenant_id, stripe_customer_id, stripe_subscription_id, plan, status
            )
            VALUES (:id, :tenant_id, :cid, :sid, :plan, :status)
            ON CONFLICT (tenant_id) DO UPDATE SET
                stripe_customer_id = COALESCE(EXCLUDED.stripe_customer_id, subscriptions.stripe_customer_id),
                stripe_subscription_id = COALESCE(EXCLUDED.stripe_subscription_id, subscriptions.stripe_subscription_id),
                plan = EXCLUDED.plan,
                status = EXCLUDED.status,
                updated_at = NOW()
            """
        ),
        {
            "id": str(sub_id),
            "tenant_id": tenant_id,
            "cid": stripe_customer_id,
            "sid": stripe_subscription_id,
            "plan": plan,
            "status": status,
        },
    )
    session.commit()


# ------------------------------------------------------------------
# Subscription status
# ------------------------------------------------------------------
@router.get("/subscription", response_model=SubscriptionResponse)
def get_subscription(
    current_user: dict = Depends(get_current_user_jwt),
    session: Session = Depends(get_session),
):
    """Get current tenant subscription status."""
    tenant_id = str(current_user["tenant_id"])
    row = session.execute(
        text(
            """
            SELECT s.plan, s.status, s.current_period_end, s.stripe_subscription_id
            FROM subscriptions s
            WHERE s.tenant_id = :tid
            """
        ),
        {"tid": tenant_id},
    ).mappings().fetchone()

    if not row:
        return SubscriptionResponse(plan="free", status="active", current_period_end=None)

    return SubscriptionResponse(
        plan=row["plan"],
        status=row["status"],
        current_period_end=row["current_period_end"].isoformat() if row["current_period_end"] else None,
        stripe_subscription_id=row["stripe_subscription_id"] or None,
    )


@router.get("/usage")
def get_usage(
    current_user: dict = Depends(get_current_user_jwt),
    session: Session = Depends(get_session),
):
    """Return current tenant plan and basic quota usage."""
    tenant_id = current_user["tenant_id"]
    plan = get_tenant_plan(session, tenant_id)
    limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
    subscription = get_tenant_subscription(session, tenant_id) or {}
    return {
        "plan": plan,
        "subscription_status": subscription.get("status", "active"),
        "max_links": limits["max_links"],
        "min_scan_frequency_seconds": limits["min_scan_frequency_seconds"],
        "current_links": count_links_for_tenant(session, tenant_id),
    }
