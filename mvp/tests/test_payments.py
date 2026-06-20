from __future__ import annotations

import os
import asyncio
import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

os.environ.setdefault("API_KEY_SECRET", "test-secret")

import api.routers.payments as payments


class _FakeRequest:
    def __init__(self, payload: bytes, signature: str = "sig"):
        self._payload = payload
        self.headers = {"stripe-signature": signature}

    async def body(self):
        return self._payload


class TestPayments(unittest.TestCase):
    def setUp(self):
        payments.STRIPE_SECRET_KEY = "sk_test"
        payments.STRIPE_WEBHOOK_SECRET = "whsec_test"
        payments.STRIPE_PRICING_TABLE_ID = "prctbl_test"
        payments.STRIPE_PUBLISHABLE_KEY = "pk_test"

    def test_list_plans_reports_enabled_plans(self):
        result = payments.list_plans()

        self.assertTrue(result["enabled"])
        self.assertEqual(result["pricing_table_id"], "prctbl_test")
        self.assertEqual(result["publishable_key"], "pk_test")
        self.assertEqual(len(result["plans"]), 3)
        self.assertTrue(any(plan["name"] == "free" and plan["enabled"] for plan in result["plans"]))
        self.assertTrue(any(plan["name"] == "pro" and plan["enabled"] for plan in result["plans"]))
        self.assertTrue(any(plan["name"] == "pro_plus" and plan["enabled"] for plan in result["plans"]))

    def test_pricing_table_endpoint_returns_embed_config(self):
        result = payments.get_pricing_table_config()

        self.assertTrue(result["enabled"])
        self.assertEqual(result["pricing_table_id"], "prctbl_test")
        self.assertEqual(result["publishable_key"], "pk_test")

    def test_usage_response_uses_plan_limits(self):
        current_user = {"tenant_id": "tenant-1"}
        session = MagicMock()

        with patch.object(payments, "get_tenant_plan", return_value="pro"), \
             patch.object(payments, "count_links_for_tenant", return_value=42), \
             patch.object(payments, "get_tenant_subscription", return_value={"status": "active"}):
            result = payments.get_usage(current_user=current_user, session=session)

        self.assertEqual(result["plan"], "pro")
        self.assertEqual(result["max_links"], payments.PLAN_LIMITS["pro"]["max_links"])
        self.assertEqual(result["current_links"], 42)

    def test_subscription_defaults_to_free_when_missing(self):
        current_user = {"tenant_id": "tenant-1"}
        session = MagicMock()
        session.execute.return_value.mappings.return_value.fetchone.return_value = None

        result = payments.get_subscription(current_user=current_user, session=session)

        self.assertEqual(result.plan, "free")
        self.assertEqual(result.status, "active")

    def test_webhook_checkout_completed_updates_subscription(self):
        event = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "customer": "cus_123",
                    "subscription": "sub_123",
                    "client_reference_id": "tenant-1",
                }
            },
        }
        fake_stripe = MagicMock()
        fake_stripe.Webhook.construct_event.return_value = event
        fake_stripe.Subscription.retrieve.return_value = {
            "items": {
                "data": [
                    {"price": {"metadata": {"plan_code": "pro"}}}
                ]
            }
        }
        session = MagicMock()

        with patch.object(payments, "_stripe_imported", return_value=fake_stripe), \
             patch.object(payments, "_upsert_subscription") as mock_upsert:
            result = asyncio.run(payments.stripe_webhook(_FakeRequest(b"{}"), session=session))

        self.assertEqual(result["status"], "ok")
        mock_upsert.assert_called_once()
        self.assertEqual(mock_upsert.call_args.kwargs["plan"], "pro")
        self.assertTrue(session.execute.called)

    def test_webhook_invoice_paid_updates_subscription(self):
        event = {
            "type": "invoice.paid",
            "data": {
                "object": {
                    "customer": "cus_456",
                    "subscription": "sub_456",
                    "client_reference_id": "tenant-2",
                }
            },
        }
        fake_stripe = MagicMock()
        fake_stripe.Webhook.construct_event.return_value = event
        fake_stripe.Subscription.retrieve.return_value = {
            "items": {
                "data": [
                    {"price": {"metadata": {"plan_code": "pro_plus"}}}
                ]
            }
        }
        session = MagicMock()

        with patch.object(payments, "_stripe_imported", return_value=fake_stripe), \
             patch.object(payments, "_upsert_subscription") as mock_upsert:
            result = asyncio.run(payments.stripe_webhook(_FakeRequest(b"{}"), session=session))

        self.assertEqual(result["status"], "ok")
        mock_upsert.assert_called_once()
        self.assertEqual(mock_upsert.call_args.kwargs["plan"], "pro_plus")

    def test_webhook_subscription_deleted_downgrades_plan(self):
        event = {
            "type": "customer.subscription.deleted",
            "data": {
                "object": {
                    "id": "sub_123",
                    "status": "canceled",
                }
            },
        }
        fake_stripe = MagicMock()
        fake_stripe.Webhook.construct_event.return_value = event
        session = MagicMock()
        session.execute.return_value.fetchone.return_value = ("tenant-1",)

        with patch.object(payments, "_stripe_imported", return_value=fake_stripe), \
             patch.object(payments, "_upsert_subscription") as mock_upsert:
            result = asyncio.run(payments.stripe_webhook(_FakeRequest(b"{}"), session=session))

        self.assertEqual(result["status"], "ok")
        mock_upsert.assert_called_once()
        self.assertTrue(session.execute.called)

    def test_webhook_subscription_updated_uses_mapped_plan(self):
        event = {
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": "sub_123",
                    "status": "trialing",
                }
            },
        }
        fake_stripe = MagicMock()
        fake_stripe.Webhook.construct_event.return_value = event
        fake_stripe.Subscription.retrieve.return_value = {
            "items": {
                "data": [
                    {"price": {"metadata": {"plan_code": "pro_plus"}}}
                ]
            }
        }
        session = MagicMock()
        session.execute.return_value.fetchone.return_value = ("tenant-1",)

        with patch.object(payments, "_stripe_imported", return_value=fake_stripe), \
             patch.object(payments, "_upsert_subscription") as mock_upsert:
            result = asyncio.run(payments.stripe_webhook(_FakeRequest(b"{}"), session=session))

        self.assertEqual(result["status"], "ok")
        mock_upsert.assert_called_once()
        self.assertEqual(mock_upsert.call_args.kwargs["plan"], "pro_plus")

    def test_webhook_rejects_bad_signature(self):
        fake_stripe = MagicMock()
        fake_stripe.Webhook.construct_event.side_effect = ValueError("No signature found")
        session = MagicMock()

        with patch.object(payments, "_stripe_imported", return_value=fake_stripe):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(
                    payments.stripe_webhook(
                        _FakeRequest(b"{}", signature=""),
                        session=session,
                    )
                )

        self.assertEqual(ctx.exception.status_code, 400)

    def test_checkout_is_disabled_in_pricing_table_mode(self):
        current_user = {"tenant_id": "tenant-1", "email": "user@example.com"}
        session = MagicMock()

        with self.assertRaises(HTTPException) as ctx:
            payments.create_checkout(plan="pro_plus", current_user=current_user, session=session)

        self.assertEqual(ctx.exception.status_code, 410)
