from __future__ import annotations

import os
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("API_KEY_SECRET", "test-secret")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from api.auth import get_session as auth_get_session
from api.main import app
from api.routers import auth as auth_router
from api.routers import issues as issues_router
from api.routers import integrations as integrations_router
from api.routers import payments as payments_router
from api.routers import projects as projects_router
from api.routers import scans as scans_router
from common import supabase_auth


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


class SupabaseAuthE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = Path(tempfile.mkdtemp(prefix="supabase-auth-e2e-"))
        cls.db_path = cls.tmpdir / "supabase-e2e.db"
        cls.engine = create_engine(
            f"sqlite+pysqlite:///{cls.db_path}",
            connect_args={"check_same_thread": False},
        )
        cls.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)
        cls._create_schema()

        cls._patchers = [
            patch.object(supabase_auth, "AUTH_MODE", "supabase"),
            patch("common.jwt_utils.decode_access_token", side_effect=cls._decode_supabase_token),
            patch("api.rate_limiter.decode_access_token", side_effect=cls._decode_supabase_token),
            patch("api.auth.decode_access_token", side_effect=cls._decode_supabase_token),
            patch("api.routers.auth.decode_access_token", side_effect=cls._decode_supabase_token),
        ]
        for patcher in cls._patchers:
            patcher.start()
        cls._rate_limit_client = _FakeRateLimitClient()
        cls._rate_limit_patcher = patch("api.rate_limiter.get_rate_limit_client", return_value=cls._rate_limit_client)
        cls._rate_limit_patcher.start()

        def db_session_override():
            db = cls.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        cls._session_override = db_session_override
        app.dependency_overrides[auth_get_session] = cls._session_override
        app.dependency_overrides[auth_router.get_session] = cls._session_override
        app.dependency_overrides[projects_router.get_session] = cls._session_override
        app.dependency_overrides[scans_router.get_session] = cls._session_override
        app.dependency_overrides[issues_router.get_session] = cls._session_override
        app.dependency_overrides[integrations_router.get_session] = cls._session_override
        app.dependency_overrides[payments_router.get_session] = cls._session_override
        cls.client = TestClient(app)

        cls.supabase_user_id = str(uuid.UUID("12345678-1234-5678-1234-567812345678"))
        cls.supabase_payload = {
            "sub": cls.supabase_user_id,
            "email": "supabase@example.com",
            "user_metadata": {"full_name": "Supabase User"},
            "role": "authenticated",
            "aud": "authenticated",
            "iss": "https://demo.supabase.co/auth/v1",
        }

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        cls._rate_limit_patcher.stop()
        for patcher in reversed(cls._patchers):
            patcher.stop()
        cls.engine.dispose()
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    @classmethod
    def _decode_supabase_token(cls, token: str):
        return dict(cls.supabase_payload)

    @classmethod
    def _create_schema(cls):
        with cls.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE tenants (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        api_key_hash TEXT,
                        plan TEXT NOT NULL DEFAULT 'free'
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE users (
                        id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        email TEXT NOT NULL UNIQUE,
                        password_hash TEXT NOT NULL DEFAULT '',
                        full_name TEXT NOT NULL DEFAULT '',
                        is_active INTEGER NOT NULL DEFAULT 1
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE subscriptions (
                        id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL UNIQUE,
                        plan TEXT NOT NULL DEFAULT 'free',
                        status TEXT NOT NULL DEFAULT 'active',
                        stripe_customer_id TEXT,
                        stripe_subscription_id TEXT,
                        current_period_start TEXT,
                        current_period_end TEXT,
                        updated_at TEXT
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE projects (
                        id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        name TEXT NOT NULL,
                        scan_frequency_seconds INTEGER NOT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE merchant_rules (
                        id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        project_id TEXT NOT NULL,
                        merchant_name TEXT NOT NULL,
                        required_tracking_keys TEXT NOT NULL DEFAULT '[]',
                        UNIQUE(project_id, merchant_name)
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE links (
                        id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        project_id TEXT NOT NULL,
                        merchant_rule_id TEXT NOT NULL,
                        source_label TEXT,
                        original_url TEXT NOT NULL
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE scans (
                        id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        project_id TEXT NOT NULL,
                        scheduled_at TEXT,
                        completed_at TEXT,
                        status TEXT NOT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )

    def api(self, method: str, path: str, **kwargs):
        return self.client.request(method, path, timeout=20, **kwargs)

    def test_supabase_auth_bootstraps_and_unlocks_dashboard_flow(self):
        headers = {"Authorization": "Bearer supabase-token"}

        auth_config = self.api("GET", "/auth/config")
        self.assertEqual(auth_config.status_code, 200, auth_config.text)
        self.assertEqual(auth_config.json()["auth_mode"], "supabase")
        self.assertFalse(auth_config.json()["local_auth_enabled"])
        self.assertTrue(auth_config.json()["supabase_mode"])

        me = self.api("GET", "/auth/me", headers=headers)
        self.assertEqual(me.status_code, 200, me.text)
        me_data = me.json()
        self.assertEqual(me_data["email"], self.supabase_payload["email"])
        self.assertEqual(me_data["full_name"], "Supabase User")

        usage = self.api("GET", "/payments/usage", headers=headers)
        self.assertEqual(usage.status_code, 200, usage.text)
        self.assertEqual(usage.json()["plan"], "free")
        self.assertEqual(usage.json()["current_links"], 0)

        project = self.api(
            "POST",
            "/projects",
            headers=headers,
            json={
                "tenant_id": me_data["tenant_id"],
                "name": "Supabase Project",
                "scan_frequency_seconds": 3600,
            },
        )
        self.assertEqual(project.status_code, 200, project.text)
        project_id = project.json()["id"]

        rule = self.api(
            "POST",
            "/projects/merchant-rules",
            headers=headers,
            json={
                "tenant_id": me_data["tenant_id"],
                "project_id": project_id,
                "merchant_name": "Amazon",
                "required_tracking_keys": [{"key": "tag", "required": True}],
            },
        )
        self.assertEqual(rule.status_code, 200, rule.text)

        links = self.api(
            "POST",
            "/projects/import-links",
            headers=headers,
            json={
                "tenant_id": me_data["tenant_id"],
                "project_id": project_id,
                "links": [
                    {
                        "merchant_name": "Amazon",
                        "original_url": "https://example.com/?tag=abc123",
                        "source_label": "Landing page",
                    }
                ],
            },
        )
        self.assertEqual(links.status_code, 200, links.text)
        self.assertEqual(links.json()["inserted"], 1)

        usage_after = self.api("GET", "/payments/usage", headers=headers)
        self.assertEqual(usage_after.status_code, 200, usage_after.text)
        self.assertEqual(usage_after.json()["current_links"], 1)

        projects = self.api("GET", "/projects", headers=headers)
        self.assertEqual(projects.status_code, 200, projects.text)
        self.assertEqual(projects.json()["total"], 1)

        me_again = self.api("GET", "/auth/me", headers=headers)
        self.assertEqual(me_again.status_code, 200, me_again.text)
        self.assertEqual(me_again.json()["tenant_id"], me_data["tenant_id"])

    def test_local_auth_routes_are_disabled_under_supabase_mode(self):
        login = self.api("POST", "/auth/login", json={"email": "a@example.com", "password": "secret123"})
        self.assertEqual(login.status_code, 410, login.text)

        register = self.api(
            "POST",
            "/auth/register",
            json={"email": "a@example.com", "password": "secret123", "full_name": "A"},
        )
        self.assertEqual(register.status_code, 410, register.text)


if __name__ == "__main__":
    unittest.main()
