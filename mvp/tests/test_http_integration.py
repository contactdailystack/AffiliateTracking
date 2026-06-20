from __future__ import annotations

import os
import time
import uuid
import unittest

import requests


BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")


class HttpIntegrationTests(unittest.TestCase):
    @classmethod
    def wait_for_api(cls, timeout_seconds: int = 90) -> None:
        deadline = time.time() + timeout_seconds
        last_error = None
        while time.time() < deadline:
            try:
                r = requests.get(f"{BASE_URL}/health", timeout=5)
                if r.status_code == 200:
                    return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
            time.sleep(2)
        raise RuntimeError(f"API not ready: {last_error}")

    @classmethod
    def setUpClass(cls):
        cls.wait_for_api()

    def api(self, method: str, path: str, **kwargs):
        return requests.request(method, f"{BASE_URL}{path}", timeout=20, **kwargs)

    def test_health_and_metrics(self):
        self.assertEqual(self.api("GET", "/health").status_code, 200)
        healthz = self.api("GET", "/healthz")
        self.assertEqual(healthz.status_code, 200)
        self.assertIn("service", healthz.json())
        self.assertEqual(self.api("GET", "/readyz").status_code, 200)
        self.assertEqual(self.api("GET", "/metrics").status_code, 200)

    def test_register_project_scan_and_usage_flow(self):
        email = f"codex-{uuid.uuid4().hex[:12]}@example.com"
        password = "Passw0rd!"

        reg = self.api("POST", "/auth/register", json={
            "email": email,
            "password": password,
            "full_name": "Codex Tester",
        })
        self.assertEqual(reg.status_code, 200, reg.text)
        data = reg.json()
        token = data["access_token"]
        tenant_id = data["tenant_id"]
        headers = {"Authorization": f"Bearer {token}"}

        me = self.api("GET", "/auth/me", headers=headers)
        self.assertEqual(me.status_code, 200, me.text)

        usage = self.api("GET", "/payments/usage", headers=headers)
        self.assertEqual(usage.status_code, 200, usage.text)

        project = self.api("POST", "/projects", headers=headers, json={
            "tenant_id": tenant_id,
            "name": "Integration Project",
            "scan_frequency_seconds": 3600,
        })
        self.assertEqual(project.status_code, 200, project.text)
        project_id = project.json()["id"]

        rule = self.api("POST", "/projects/merchant-rules", headers=headers, json={
            "tenant_id": tenant_id,
            "project_id": project_id,
            "merchant_name": "Amazon",
            "required_tracking_keys": [{"key": "tag", "required": True}],
        })
        self.assertEqual(rule.status_code, 200, rule.text)

        links = self.api("POST", "/projects/import-links", headers=headers, json={
            "tenant_id": tenant_id,
            "project_id": project_id,
            "links": [
                {"merchant_name": "Amazon", "original_url": "https://example.com/?tag=abc123", "source_label": "Landing page"}
            ],
        })
        self.assertEqual(links.status_code, 200, links.text)

        scans = self.api("POST", "/scans/start", headers=headers, json={"project_id": project_id})
        self.assertEqual(scans.status_code, 200, scans.text)

        history = self.api("GET", "/scans/history", headers=headers, params={"project_id": project_id})
        self.assertEqual(history.status_code, 200, history.text)
        self.assertGreaterEqual(history.json()["total"], 1)

        projects = self.api("GET", "/projects", headers=headers)
        self.assertEqual(projects.status_code, 200, projects.text)

        issues = self.api("GET", "/issues", headers=headers, params={"project_id": project_id})
        self.assertEqual(issues.status_code, 200, issues.text)

    def test_readyz_depends_on_services(self):
        r = self.api("GET", "/readyz")
        self.assertIn(r.status_code, (200, 503))
