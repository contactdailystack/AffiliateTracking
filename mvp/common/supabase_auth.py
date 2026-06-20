from __future__ import annotations

import base64
import json
import os
import time
from typing import Any, Optional

import httpx
from jose import JWTError, jwk, jwt

AUTH_MODE = os.getenv("AUTH_MODE", "local").lower()
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_JWKS_URL = os.getenv("SUPABASE_JWKS_URL", "")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")
SUPABASE_JWT_ISSUER = os.getenv("SUPABASE_JWT_ISSUER", "")
SUPABASE_JWT_AUDIENCE = os.getenv("SUPABASE_JWT_AUDIENCE", "authenticated")
SUPABASE_JWKS_CACHE_SECONDS = int(os.getenv("SUPABASE_JWKS_CACHE_SECONDS", "600"))

_JWKS_CACHE: dict[str, Any] = {"fetched_at": 0.0, "keys": []}


def _project_jwks_url() -> str | None:
    if SUPABASE_JWKS_URL:
        return SUPABASE_JWKS_URL
    if SUPABASE_URL:
        return f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
    return None


def _base64url_decode(raw: str) -> bytes:
    padding = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(raw + padding)


def _get_jwks() -> list[dict[str, Any]]:
    url = _project_jwks_url()
    if not url:
        return []
    now = time.time()
    if _JWKS_CACHE["keys"] and now - float(_JWKS_CACHE["fetched_at"]) < SUPABASE_JWKS_CACHE_SECONDS:
        return list(_JWKS_CACHE["keys"])

    response = httpx.get(url, timeout=10)
    response.raise_for_status()
    payload = response.json()
    keys = payload.get("keys", []) if isinstance(payload, dict) else []
    _JWKS_CACHE["keys"] = keys
    _JWKS_CACHE["fetched_at"] = now
    return list(keys)


def verify_supabase_token(token: str) -> Optional[dict[str, Any]]:
    try:
        header = jwt.get_unverified_header(token)
        claims = jwt.get_unverified_claims(token)
        alg = header.get("alg")
        if not alg:
            return None

        if SUPABASE_JWT_SECRET and alg.startswith("HS"):
            options = {"verify_aud": bool(SUPABASE_JWT_AUDIENCE)}
            kwargs: dict[str, Any] = {"algorithms": [alg], "options": options}
            if SUPABASE_JWT_ISSUER:
                kwargs["issuer"] = SUPABASE_JWT_ISSUER
            if SUPABASE_JWT_AUDIENCE:
                kwargs["audience"] = SUPABASE_JWT_AUDIENCE
            return jwt.decode(token, SUPABASE_JWT_SECRET, **kwargs)

        kid = header.get("kid")
        keys = _get_jwks()
        if not keys or not kid:
            return None

        jwk_data = next((item for item in keys if item.get("kid") == kid), None)
        if not jwk_data:
            return None

        key = jwk.construct(jwk_data, alg)
        message, encoded_signature = token.rsplit(".", 1)
        if not key.verify(message.encode(), _base64url_decode(encoded_signature)):
            return None

        issuer = SUPABASE_JWT_ISSUER or claims.get("iss")
        audience = SUPABASE_JWT_AUDIENCE
        if issuer and claims.get("iss") != issuer:
            return None
        if audience:
            token_aud = claims.get("aud")
            if isinstance(token_aud, list):
                if audience not in token_aud:
                    return None
            elif token_aud not in (audience, None):
                return None
        exp = claims.get("exp")
        if isinstance(exp, (int, float)) and exp < time.time():
            return None
        return claims
    except (JWTError, httpx.HTTPError, ValueError, json.JSONDecodeError):
        return None


def is_supabase_mode() -> bool:
    return AUTH_MODE == "supabase"
