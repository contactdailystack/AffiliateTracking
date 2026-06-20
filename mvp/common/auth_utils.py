# mvp/common/auth_utils.py
"""API key generation and verification utilities."""
from __future__ import annotations

import hmac
import hashlib
import os
import secrets

_SECRET = os.getenv("API_KEY_SECRET")
if not _SECRET:
    raise ValueError("API_KEY_SECRET environment variable is missing or empty!")


def generate_api_key() -> tuple[str, str]:
    """Generate a new random API key and its hash.

    Returns:
        (raw_key, key_hash) — raw_key should be shown ONCE to the user.
    """
    raw_key = secrets.token_urlsafe(32)
    key_hash = _hash_key(raw_key)
    return raw_key, key_hash


def _hash_key(raw_key: str) -> str:
    """Hash a raw API key using HMAC-SHA256."""
    return hmac.new(_SECRET.encode(), raw_key.encode(), hashlib.sha256).hexdigest()


def verify_api_key(raw_key: str, key_hash: str) -> bool:
    """Verify that a raw API key matches a stored hash."""
    if not raw_key or not key_hash:
        return False
    return hmac.compare_digest(_hash_key(raw_key), key_hash)
