from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote

import httpx

UPSTASH_REDIS_REST_URL = os.getenv("UPSTASH_REDIS_REST_URL", "").rstrip("/")
UPSTASH_REDIS_REST_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")


class UpstashRedisRestClient:
    def __init__(self, base_url: str, token: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _request(self, method: str, path: str) -> Any:
        headers = {"Authorization": f"Bearer {self.token}"}
        response = httpx.request(method, f"{self.base_url}{path}", headers=headers, timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and "result" in payload:
            return payload["result"]
        return payload

    def ping(self) -> bool:
        result = self._request("GET", "/ping")
        return str(result).upper() in {"PONG", "OK", "TRUE"}

    def zremrangebyscore(self, key: str, min_score: float, max_score: float) -> Any:
        return self._request(
            "POST",
            f"/zremrangebyscore/{quote(key, safe='')}/{min_score}/{max_score}",
        )

    def zcard(self, key: str) -> int:
        result = self._request("GET", f"/zcard/{quote(key, safe='')}")
        return int(result or 0)

    def zadd(self, key: str, score: float, member: str) -> Any:
        return self._request(
            "POST",
            f"/zadd/{quote(key, safe='')}/{score}/{quote(member, safe='')}",
        )

    def expire(self, key: str, seconds: int) -> Any:
        return self._request("POST", f"/expire/{quote(key, safe='')}/{seconds}")


def get_rate_limit_client() -> UpstashRedisRestClient | None:
    if not UPSTASH_REDIS_REST_URL or not UPSTASH_REDIS_REST_TOKEN:
        return None
    return UpstashRedisRestClient(UPSTASH_REDIS_REST_URL, UPSTASH_REDIS_REST_TOKEN)


def ping_upstash() -> bool:
    client = get_rate_limit_client()
    return client.ping() if client else False
