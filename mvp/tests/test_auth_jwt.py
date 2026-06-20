from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch
from uuid import UUID

os.environ.setdefault("API_KEY_SECRET", "test-secret")

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from api.auth import get_current_user_jwt
from common.jwt_utils import create_access_token


class TestJwtAuth(unittest.TestCase):
    def test_get_current_user_jwt_returns_user(self):
        token = create_access_token(
            user_id="11111111-1111-1111-1111-111111111111",
            tenant_id="22222222-2222-2222-2222-222222222222",
            email="user@example.com",
        )
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        session = MagicMock()
        row = {
            "id": UUID("11111111-1111-1111-1111-111111111111"),
            "tenant_id": UUID("22222222-2222-2222-2222-222222222222"),
            "email": "user@example.com",
            "full_name": "User",
            "is_active": True,
            "plan": "pro",
            "tenant_name": "Demo",
        }
        session.execute.return_value.mappings.return_value.fetchone.return_value = row

        result = get_current_user_jwt(credentials=credentials, session=session)

        self.assertEqual(result["email"], "user@example.com")
        self.assertEqual(result["plan"], "pro")
        self.assertEqual(result["tenant_name"], "Demo")

    def test_get_current_user_jwt_rejects_invalid_token(self):
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="bad-token")
        session = MagicMock()

        with self.assertRaises(HTTPException):
            get_current_user_jwt(credentials=credentials, session=session)

    def test_get_current_user_jwt_supports_email_only_payload(self):
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="supabase-token")
        session = MagicMock()
        row = {
            "id": UUID("11111111-1111-1111-1111-111111111111"),
            "tenant_id": UUID("22222222-2222-2222-2222-222222222222"),
            "email": "supabase@example.com",
            "full_name": "Supabase User",
            "is_active": True,
            "plan": "pro",
            "tenant_name": "Demo",
        }
        session.execute.return_value.mappings.return_value.fetchone.return_value = row

        with patch("api.auth.decode_access_token", return_value={"email": "supabase@example.com"}):
            result = get_current_user_jwt(credentials=credentials, session=session)

        self.assertEqual(result["email"], "supabase@example.com")
        self.assertEqual(result["tenant_name"], "Demo")

    def test_local_auth_is_disabled_in_supabase_mode(self):
        from api.routers import auth as auth_router

        session = MagicMock()

        with patch.object(auth_router, "is_supabase_mode", return_value=True):
            with self.assertRaises(HTTPException) as ctx:
                auth_router.login(auth_router.LoginRequest(email="a@example.com", password="secret123"), session=session)

            self.assertEqual(ctx.exception.status_code, 503)

            with self.assertRaises(HTTPException) as ctx2:
                auth_router.register(
                    auth_router.RegisterRequest(email="a@example.com", password="secret123", full_name="A"),
                    session=session,
                )

            self.assertEqual(ctx2.exception.status_code, 503)
