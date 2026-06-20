from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch
from uuid import UUID

os.environ.setdefault("API_KEY_SECRET", "test-secret")

from fastapi.testclient import TestClient

from api.main import app
from api.routers import projects as projects_router
from api.routers import scans as scans_router
from api.routers import issues as issues_router
from api.routers import integrations as integrations_router
from api.routers import payments as payments_router


class _FakeRateLimitClient:
    def __init__(self):
        self.store = {}

    def zremrangebyscore(self, key, min_score, max_score):
        items = self.store.get(key, [])
        self.store[key] = [(score, member) for score, member in items if not (min_score <= score <= max_score)]

    def zcard(self, key):
        return len(self.store.get(key, []))

    def zadd(self, key, score, member):
        self.store.setdefault(key, []).append((score, member))

    def expire(self, key, seconds):
        return True

    def ping(self):
        return True


class TestApiRoutes(unittest.TestCase):
    def setUp(self):
        self.current_user = {
            "id": UUID("11111111-1111-1111-1111-111111111111"),
            "tenant_id": UUID("22222222-2222-2222-2222-222222222222"),
            "email": "user@example.com",
            "full_name": "Demo User",
            "plan": "pro",
            "tenant_name": "Demo",
        }
        self.current_user_override = lambda: self.current_user
        self.session_override = lambda: MagicMock()
        app.dependency_overrides[projects_router.get_current_user_jwt] = self.current_user_override
        app.dependency_overrides[scans_router.get_current_user_jwt] = self.current_user_override
        app.dependency_overrides[issues_router.get_current_user_jwt] = self.current_user_override
        app.dependency_overrides[payments_router.get_current_user_jwt] = self.current_user_override
        app.dependency_overrides[projects_router.get_session] = self.session_override
        app.dependency_overrides[scans_router.get_session] = self.session_override
        app.dependency_overrides[issues_router.get_session] = self.session_override
        app.dependency_overrides[integrations_router.get_session] = self.session_override
        app.dependency_overrides[payments_router.get_session] = self.session_override
        app.dependency_overrides[integrations_router.get_api_key_tenant] = lambda: self.current_user["tenant_id"]
        self._rate_limit_client = _FakeRateLimitClient()
        self._rate_limit_patcher = patch("api.rate_limiter.get_rate_limit_client", return_value=self._rate_limit_client)
        self._rate_limit_patcher.start()
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self._rate_limit_patcher.stop()

    def test_usage_and_projects_and_scan_routes(self):
        with patch("api.routers.projects.services.list_tenant_projects", return_value=[]), \
             patch("api.routers.projects.services.create_project", return_value=UUID("33333333-3333-3333-3333-333333333333")), \
             patch("api.routers.projects.services.ensure_project_ownership", return_value=True), \
             patch("api.routers.projects.services.set_merchant_rule", return_value=UUID("44444444-4444-4444-4444-444444444444")), \
             patch("api.routers.projects.services.import_links", return_value=1), \
             patch("api.routers.scans.services.check_scan_allowed", return_value=(True, "")), \
             patch("api.routers.scans.services.ensure_project_ownership", return_value=True), \
             patch("api.routers.scans.tasks.enqueue_scan_project", return_value=MagicMock(id="task-1")) as mock_enqueue_scan, \
             patch("api.routers.scans.create_scan_record", return_value=UUID("55555555-5555-5555-5555-555555555555")), \
             patch("api.routers.integrations.services.ensure_project_ownership", return_value=True), \
             patch("api.routers.integrations.services.import_links", return_value=2) as mock_wordpress_sync, \
             patch("api.routers.payments.get_tenant_plan", return_value="pro"), \
             patch("api.routers.payments.count_links_for_tenant", return_value=12), \
             patch("api.routers.payments.get_tenant_subscription", return_value={"status": "active"}):
            response = self.client.get("/payments/usage")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["plan"], "pro")

            response = self.client.get("/auth/config")
            self.assertEqual(response.status_code, 200)
            self.assertIn("auth_mode", response.json())

            response = self.client.get("/projects")
            self.assertEqual(response.status_code, 200)

            response = self.client.post("/projects", json={
                "tenant_id": str(self.current_user["tenant_id"]),
                "name": "Alpha",
                "scan_frequency_seconds": 3600,
            })
            self.assertEqual(response.status_code, 200)

            response = self.client.post("/projects/merchant-rules", json={
                "tenant_id": str(self.current_user["tenant_id"]),
                "project_id": str(self.current_user["tenant_id"]),
                "merchant_name": "Amazon",
                "required_tracking_keys": [{"key": "tag", "required": True}],
            })
            self.assertIn(response.status_code, (200, 403))

            response = self.client.post("/projects/import-links", json={
                "tenant_id": str(self.current_user["tenant_id"]),
                "project_id": str(self.current_user["tenant_id"]),
                "links": [{"merchant_name": "Amazon", "original_url": "https://example.com"}],
            })
            self.assertIn(response.status_code, (200, 403))

            response = self.client.post("/scans/start", json={
                "project_id": str(self.current_user["tenant_id"]),
            })
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["queued"], True)
            mock_enqueue_scan.assert_called_once()
            self.assertEqual(mock_enqueue_scan.call_args.kwargs["scan_variants"], [])

            response = self.client.post("/integrations/wordpress/sync-links", json={
                "project_id": str(self.current_user["tenant_id"]),
                "merchant_name": "Amazon",
                "links": [
                    {"merchant_name": "Amazon", "original_url": "https://example.com/a", "source_label": "Post"}
                ],
            }, headers={"X-API-Key": "test-key"})
            self.assertEqual(response.status_code, 200)
            mock_wordpress_sync.assert_called_once()

            response = self.client.post("/tenants", json={"name": "Blocked"})
            self.assertIn(response.status_code, (404, 410))

    def test_issue_routes_and_auth_smoke(self):
        issue_row = {
            "id": UUID("66666666-6666-6666-6666-666666666666"),
            "tenant_id": self.current_user["tenant_id"],
            "project_id": UUID("77777777-7777-7777-7777-777777777777"),
            "link_id": UUID("88888888-8888-8888-8888-888888888888"),
            "merchant_rule_id": UUID("99999999-9999-9999-9999-999999999999"),
            "issue_type": "404",
            "severity": 3,
            "status": "open",
            "evidence": {"original_url": "https://example.com/broken"},
            "first_seen_at": None,
            "last_seen_at": None,
            "resolved_at": None,
        }

        with patch("api.routers.issues.services.ensure_project_ownership", return_value=True), \
             patch("api.routers.issues.services.list_project_issues", return_value=[issue_row]), \
             patch("api.routers.issues.services.get_issue", return_value=issue_row), \
             patch("api.routers.issues.services.resolve_issue", return_value={**issue_row, "resolved_at": "2026-06-20T00:00:00Z"}):
            response = self.client.get("/issues", params={"project_id": str(issue_row["project_id"])})
            self.assertEqual(response.status_code, 200)

            response = self.client.get(f"/issues/{issue_row['id']}")
            self.assertEqual(response.status_code, 200)

            response = self.client.patch(f"/issues/{issue_row['id']}", json={"reason": "fixed"})
            self.assertEqual(response.status_code, 200)
