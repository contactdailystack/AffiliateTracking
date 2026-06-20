import os
import time
from uuid import uuid4

import logging

from fastapi import HTTPException, Request
from redis import Redis

from ..common.jwt_utils import decode_access_token
from ..common.upstash_rest import get_rate_limit_client
from ..common.observability import record_rate_limit_failure

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
redis_client = Redis.from_url(REDIS_URL)
logger = logging.getLogger(__name__)


def rate_limit(requests_limit: int, window_seconds: int):
    """FastAPI dependency for sliding-window rate limiting using Redis."""
    def dependency(request: Request):
        # Prefer JWT identity for authenticated endpoints, then fall back to API key/IP.
        client_ip = request.client.host if request.client else "unknown"
        auth_header = request.headers.get("Authorization", "")
        api_key = request.headers.get("X-API-Key")
        identifier = f"rate_limit:{client_ip}"

        if auth_header.startswith("Bearer "):
            token = auth_header.removeprefix("Bearer ").strip()
            payload = decode_access_token(token)
            if payload:
                sub = payload.get("sub") or "unknown"
                tenant_id = payload.get("tenant_id") or "unknown"
                identifier = f"rate_limit:jwt:{tenant_id}:{sub}"
        elif api_key:
            identifier = f"rate_limit:api_key:{api_key}"

        now = time.time()
        clear_before = now - window_seconds

        try:
            upstash_client = get_rate_limit_client()
            if upstash_client:
                upstash_client.zremrangebyscore(identifier, 0, clear_before)
                current_requests = upstash_client.zcard(identifier)
                if current_requests < requests_limit:
                    upstash_client.zadd(identifier, now, f"{now}:{uuid4().hex}")
                    upstash_client.expire(identifier, window_seconds)
            else:
                pipe = redis_client.pipeline()
                pipe.zremrangebyscore(identifier, 0, clear_before)
                pipe.zcard(identifier)
                _, current_requests, _, _ = pipe.execute()
                if current_requests < requests_limit:
                    pipe = redis_client.pipeline()
                    pipe.zadd(identifier, {f"{now}:{uuid4().hex}": now})
                    pipe.expire(identifier, window_seconds)
                    pipe.execute()

            if current_requests >= requests_limit:
                raise HTTPException(
                    status_code=429,
                    detail="Too many requests. Please try again later.",
                )
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Rate limit dependency failed closed: %s", exc)
            record_rate_limit_failure(type(exc).__name__)
            raise HTTPException(status_code=503, detail="Rate limit service unavailable")

    return dependency
