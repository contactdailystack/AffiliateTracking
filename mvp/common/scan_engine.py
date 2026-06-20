# mvp/common/scan_engine.py
"""Core scanning logic for affiliate link integrity checks.

Follows redirects, checks tracking parameters, and classifies issues.
"""

from __future__ import annotations

import fnmatch
import ipaddress
import os
import socket
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx


@dataclass
class RedirectHop:
    url: str
    status_code: int


@dataclass
class ScanResult:
    link_id: str
    original_url: str
    variant_name: str = "default"
    variant_meta: Dict[str, Any] = field(default_factory=dict)
    final_url: Optional[str] = None
    redirect_chain: List[RedirectHop] = field(default_factory=list)
    http_status: Optional[int] = None
    issue_type: Optional[str] = None
    severity: int = 0
    missing_params: List[str] = field(default_factory=list)
    error_message: Optional[str] = None


class IssueType:
    """Canonical issue categories for the rule engine."""

    NOT_FOUND = "404"
    REDIRECT_LOOP = "redirect_loop"
    SSRF_BLOCKED = "ssrf_blocked"
    TRACKING_PARAM_LOST = "tracking_param_lost"
    SSL_ERROR = "ssl_error"
    DOMAIN_ERROR = "domain_error"
    TIMEOUT = "timeout"
    OTHER = "other"


@dataclass
class ScanVariant:
    name: str = "default"
    user_agent: Optional[str] = None
    accept_language: Optional[str] = None
    geo_label: Optional[str] = None
    proxy_url: Optional[str] = None
    device: str = "desktop"

    def headers(self) -> Dict[str, str]:
        headers = {"User-Agent": self.user_agent or "AffiliateMVP-IntegrityBot/1.0"}
        if self.accept_language:
            headers["Accept-Language"] = self.accept_language
        if self.device == "mobile":
            headers["Sec-CH-UA-Mobile"] = "?1"
        return headers

    def meta(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "geo_label": self.geo_label,
            "device": self.device,
            "proxy_url": self.proxy_url,
            "user_agent": self.user_agent,
            "accept_language": self.accept_language,
        }


def _csv_list(env_name: str) -> list[str]:
    value = os.getenv(env_name, "")
    return [item.strip().lower().rstrip(".") for item in value.split(",") if item.strip()]


SCAN_ALLOWED_HOSTS = _csv_list("SCAN_ALLOWED_HOSTS")
SCAN_DENIED_HOSTS = _csv_list("SCAN_DENIED_HOSTS")
SCAN_ALLOWED_CIDRS = [ipaddress.ip_network(item, strict=False) for item in _csv_list("SCAN_ALLOWED_CIDRS")]
SCAN_DENIED_CIDRS = [ipaddress.ip_network(item, strict=False) for item in _csv_list("SCAN_DENIED_CIDRS")]
SCAN_ALLOW_PROXY_URLS = os.getenv("SCAN_ALLOW_PROXY_URLS", "false").lower() == "true"
SCAN_BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "metadata",
    "metadata.google.internal",
}


def _host_matches(host: str, pattern: str) -> bool:
    host = host.lower().rstrip(".")
    pattern = pattern.lower().rstrip(".")
    return fnmatch.fnmatch(host, pattern) or host == pattern or host.endswith(f".{pattern}")


def _is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or ip.is_site_local
    )


def _resolve_host_ips(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    ips: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in infos:
        addr = info[4][0]
        try:
            ips.append(ipaddress.ip_address(addr))
        except ValueError:
            continue
    return ips


def _validate_host_or_ip(host: str, purpose: str) -> None:
    normalized = host.strip().lower().rstrip(".")
    if not normalized:
        raise ValueError(f"{purpose} host is empty")
    if normalized in SCAN_BLOCKED_HOSTNAMES or normalized.endswith(".localhost"):
        raise ValueError(f"{purpose} host '{host}' is blocked")
    if any(_host_matches(normalized, pattern) for pattern in SCAN_DENIED_HOSTS):
        raise ValueError(f"{purpose} host '{host}' is denylisted")

    is_ip_literal = False
    try:
        ip = ipaddress.ip_address(normalized)
        is_ip_literal = True
    except ValueError:
        ip = None

    if is_ip_literal:
        if not _is_public_ip(ip):
            raise ValueError(f"{purpose} IP '{host}' is private, loopback, or reserved")
        if SCAN_ALLOWED_CIDRS and not any(ip in cidr for cidr in SCAN_ALLOWED_CIDRS):
            raise ValueError(f"{purpose} IP '{host}' is not allowlisted")
        if any(ip in cidr for cidr in SCAN_DENIED_CIDRS):
            raise ValueError(f"{purpose} IP '{host}' is denylisted")
        return

    if SCAN_ALLOWED_HOSTS and not any(_host_matches(normalized, pattern) for pattern in SCAN_ALLOWED_HOSTS):
        raise ValueError(f"{purpose} host '{host}' is not allowlisted")

    ips = _resolve_host_ips(normalized)
    if not ips:
        raise ValueError(f"{purpose} host '{host}' could not be resolved")

    for resolved_ip in ips:
        if not _is_public_ip(resolved_ip):
            raise ValueError(f"{purpose} host '{host}' resolves to blocked IP '{resolved_ip}'")
        if any(resolved_ip in cidr for cidr in SCAN_DENIED_CIDRS):
            raise ValueError(f"{purpose} host '{host}' resolves to denylisted IP '{resolved_ip}'")
        if SCAN_ALLOWED_CIDRS and not any(resolved_ip in cidr for cidr in SCAN_ALLOWED_CIDRS):
            raise ValueError(f"{purpose} host '{host}' resolves outside allowlisted ranges")


def _validate_scan_url(url: str, purpose: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"{purpose} URL scheme '{parsed.scheme}' is not allowed")
    if not parsed.hostname:
        raise ValueError(f"{purpose} URL has no hostname")
    _validate_host_or_ip(parsed.hostname, purpose)


def _fetch_with_redirect_validation(
    client: httpx.Client,
    original_url: str,
    max_redirects: int,
) -> tuple[httpx.Response, list[RedirectHop]]:
    current_url = original_url
    redirect_chain: list[RedirectHop] = []

    for _ in range(max_redirects + 1):
        _validate_scan_url(current_url, "target")
        response = client.get(current_url, follow_redirects=False)
        redirect_chain.append(RedirectHop(url=str(response.url), status_code=response.status_code))

        if response.status_code not in (301, 302, 303, 307, 308):
            return response, redirect_chain

        location = response.headers.get("location")
        if not location:
            return response, redirect_chain

        next_url = urllib.parse.urljoin(str(response.url), location)
        _validate_scan_url(next_url, "redirect target")
        current_url = next_url

    raise httpx.TooManyRedirects("Too many redirects (possible redirect loop)")


def _check_tracking_params(final_url: str, required_keys: List[Dict[str, Any]]) -> List[str]:
    """Return list of required tracking keys missing from the final URL."""
    if not final_url:
        return []

    parsed = urllib.parse.urlparse(final_url)
    params = urllib.parse.parse_qs(parsed.query)
    missing: List[str] = []

    for item in required_keys:
        key = item.get("key")
        required = item.get("required", False)
        if required and key and key not in params:
            missing.append(key)

    return missing


def scan_link(
    original_url: str,
    link_id: str,
    required_tracking_keys: Optional[List[Dict[str, Any]]] = None,
    scan_variant: Optional[Dict[str, Any]] = None,
    max_redirects: int = 10,
    timeout: float = 30.0,
) -> ScanResult:
    """Fetch a URL, follow redirects, and classify any integrity issues.

    Args:
        original_url: The affiliate link to scan.
        link_id: DB identifier for this link (echoed back in result).
        required_tracking_keys: List of dicts like [{"key": "tag", "required": True}].
        max_redirects: Hard limit on redirect hops (MVP safety guard).
        timeout: Request timeout in seconds.
    """
    if required_tracking_keys is None:
        required_tracking_keys = []

    redirect_chain: List[RedirectHop] = []
    final_url: Optional[str] = None
    http_status: Optional[int] = None
    issue_type: Optional[str] = None
    severity = 0
    missing_params: List[str] = []
    error_message: Optional[str] = None
    variant = ScanVariant(**scan_variant) if scan_variant else ScanVariant()

    try:
        _validate_scan_url(original_url, "target")
        if variant.proxy_url:
            if not SCAN_ALLOW_PROXY_URLS:
                raise ValueError("proxy_url is disabled in this environment")
            _validate_scan_url(variant.proxy_url, "proxy")

        client_kwargs: Dict[str, Any] = {
            "timeout": httpx.Timeout(timeout),
            "headers": variant.headers(),
        }
        if variant.proxy_url:
            client_kwargs["proxy"] = variant.proxy_url

        with httpx.Client(**client_kwargs) as client:
            response, redirect_chain = _fetch_with_redirect_validation(
                client=client,
                original_url=original_url,
                max_redirects=max_redirects,
            )

            final_url = str(response.url)
            http_status = response.status_code

            # HTTP-level failures
            if response.status_code >= 400:
                if response.status_code in (404, 410):
                    issue_type = IssueType.NOT_FOUND
                    severity = 3
                elif response.status_code >= 500:
                    issue_type = IssueType.OTHER
                    severity = 2
                else:
                    issue_type = IssueType.OTHER
                    severity = 2
                error_message = f"HTTP {response.status_code}"
            else:
                # Check tracking-parameter integrity on the final URL
                missing_params = _check_tracking_params(final_url, required_tracking_keys)
                if missing_params:
                    issue_type = IssueType.TRACKING_PARAM_LOST
                    severity = 2
                    error_message = f"Missing required tracking params: {missing_params}"

    except httpx.TooManyRedirects:
        issue_type = IssueType.REDIRECT_LOOP
        severity = 3
        error_message = "Too many redirects (possible redirect loop)"
    except ValueError as exc:
        issue_type = IssueType.SSRF_BLOCKED
        severity = 3
        error_message = str(exc)
    except httpx.TimeoutException:
        issue_type = IssueType.TIMEOUT
        severity = 2
        error_message = "Request timeout"
    except (httpx.ConnectError, httpx.NetworkError) as exc:
        err_str = str(exc).lower()
        if "ssl" in err_str or "certificate" in err_str:
            issue_type = IssueType.SSL_ERROR
            severity = 3
        elif any(x in err_str for x in ("dns", "getaddrinfo", "name resolution", "no address")):
            issue_type = IssueType.DOMAIN_ERROR
            severity = 3
        else:
            # Connection refused, unreachable, etc. — treat as domain-side for MVP
            issue_type = IssueType.DOMAIN_ERROR
            severity = 3
        error_message = str(exc)
    except Exception as exc:  # noqa: BLE001
        issue_type = IssueType.OTHER
        severity = 1
        error_message = f"Unexpected error: {exc}"

    return ScanResult(
        link_id=link_id,
        original_url=original_url,
        variant_name=variant.name,
        variant_meta=variant.meta(),
        final_url=final_url,
        redirect_chain=redirect_chain,
        http_status=http_status,
        issue_type=issue_type,
        severity=severity,
        missing_params=missing_params,
        error_message=error_message,
    )
