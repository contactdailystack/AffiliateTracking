from __future__ import annotations

import logging
from collections import Counter
from threading import Lock

_LOCK = Lock()
_REQUESTS = Counter()
_LATENCY_SUM = Counter()
_RATE_LIMIT_FAILURES = Counter()


def configure_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )


def record_request(method: str, path: str, status_code: int, duration_seconds: float) -> None:
    key = (method.upper(), path, str(status_code))
    with _LOCK:
        _REQUESTS[key] += 1
        _LATENCY_SUM[key] += duration_seconds


def record_rate_limit_failure(source: str) -> None:
    with _LOCK:
        _RATE_LIMIT_FAILURES[source] += 1


def render_metrics() -> str:
    lines: list[str] = [
        "# HELP mvp_http_requests_total Total HTTP requests",
        "# TYPE mvp_http_requests_total counter",
    ]
    with _LOCK:
        for (method, path, status), count in sorted(_REQUESTS.items()):
            lines.append(
                f'mvp_http_requests_total{{method="{method}",path="{path}",status="{status}"}} {count}'
            )
        lines += [
            "# HELP mvp_http_request_duration_seconds_sum Request duration sum",
            "# TYPE mvp_http_request_duration_seconds_sum counter",
        ]
        for (method, path, status), total in sorted(_LATENCY_SUM.items()):
            lines.append(
                f'mvp_http_request_duration_seconds_sum{{method="{method}",path="{path}",status="{status}"}} {total:.6f}'
            )
        lines += [
            "# HELP mvp_rate_limit_failures_total Rate limit dependency failures",
            "# TYPE mvp_rate_limit_failures_total counter",
        ]
        for source, count in sorted(_RATE_LIMIT_FAILURES.items()):
            lines.append(f'mvp_rate_limit_failures_total{{source="{source}"}} {count}')
    return "\n".join(lines) + "\n"
