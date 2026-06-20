# mvp/tests/test_scan_engine.py
"""Unit tests for the scan engine (rule engine classification)."""
from __future__ import annotations
import unittest
import ipaddress
from unittest.mock import patch, MagicMock
import httpx

from common.scan_engine import scan_link, IssueType


class MockResponse:
    def __init__(self, status_code, url, history=None, headers=None):
        self.status_code = status_code
        self.url = url
        self.history = history or []
        self.headers = headers or {}


class TestScanEngine(unittest.TestCase):
    def setUp(self):
        self._resolve_patch = patch("common.scan_engine._resolve_host_ips", return_value=[ipaddress.ip_address("93.184.216.34")])
        self._resolve_patch.start()

    def tearDown(self):
        self._resolve_patch.stop()

    def _mock_client(self, status_code=200, final_url="https://example.com/final", history=None):
        client = MagicMock()
        response = MockResponse(status_code, final_url, history or [])
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        client.get = MagicMock(return_value=response)
        return client

    @patch("common.scan_engine.httpx.Client")
    def test_no_issue_healthy_link(self, mock_client_cls):
        mock_client_cls.return_value = self._mock_client(200, "https://example.com/landing?tag=abc123")
        result = scan_link(
            "https://example.com/affiliate?tag=abc123",
            "link-1",
            required_tracking_keys=[{"key": "tag", "required": True}],
        )
        self.assertIsNone(result.issue_type)
        self.assertEqual(result.http_status, 200)
        self.assertEqual(result.final_url, "https://example.com/landing?tag=abc123")

    @patch("common.scan_engine.httpx.Client")
    def test_404_not_found(self, mock_client_cls):
        mock_client_cls.return_value = self._mock_client(404, "https://example.com/notfound")
        result = scan_link("https://example.com/affiliate", "link-2")
        self.assertEqual(result.issue_type, IssueType.NOT_FOUND)
        self.assertEqual(result.severity, 3)
        self.assertEqual(result.http_status, 404)

    @patch("common.scan_engine.httpx.Client")
    def test_500_server_error(self, mock_client_cls):
        mock_client_cls.return_value = self._mock_client(500, "https://example.com/error")
        result = scan_link("https://example.com/affiliate", "link-3")
        self.assertEqual(result.issue_type, IssueType.OTHER)
        self.assertEqual(result.severity, 2)
        self.assertEqual(result.http_status, 500)

    @patch("common.scan_engine.httpx.Client")
    def test_redirect_loop(self, mock_client_cls):
        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        client.get = MagicMock(side_effect=httpx.TooManyRedirects("Too many redirects"))
        mock_client_cls.return_value = client

        result = scan_link("https://example.com/loop", "link-4")
        self.assertEqual(result.issue_type, IssueType.REDIRECT_LOOP)
        self.assertEqual(result.severity, 3)
        self.assertEqual(result.error_message, "Too many redirects (possible redirect loop)")

    @patch("common.scan_engine.httpx.Client")
    def test_tracking_param_lost(self, mock_client_cls):
        # Final URL missing required 'tag' parameter
        mock_client_cls.return_value = self._mock_client(200, "https://example.com/landing?other=1")
        result = scan_link(
            "https://example.com/affiliate?tag=abc123",
            "link-5",
            required_tracking_keys=[{"key": "tag", "required": True}],
        )
        self.assertEqual(result.issue_type, IssueType.TRACKING_PARAM_LOST)
        self.assertEqual(result.severity, 2)
        self.assertIn("tag", result.missing_params)

    @patch("common.scan_engine.httpx.Client")
    def test_tracking_param_preserved(self, mock_client_cls):
        # Final URL still has the required 'tag' parameter
        mock_client_cls.return_value = self._mock_client(200, "https://example.com/landing?tag=abc123&extra=1")
        result = scan_link(
            "https://example.com/affiliate?tag=abc123",
            "link-6",
            required_tracking_keys=[{"key": "tag", "required": True}],
        )
        self.assertIsNone(result.issue_type)

    @patch("common.scan_engine.httpx.Client")
    def test_ssl_error(self, mock_client_cls):
        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        client.get = MagicMock(side_effect=httpx.ConnectError("SSL certificate verify failed"))
        mock_client_cls.return_value = client

        result = scan_link("https://example.com/affiliate", "link-7")
        self.assertEqual(result.issue_type, IssueType.SSL_ERROR)
        self.assertEqual(result.severity, 3)

    @patch("common.scan_engine.httpx.Client")
    def test_domain_error(self, mock_client_cls):
        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        client.get = MagicMock(side_effect=httpx.ConnectError("getaddrinfo failed: No address associated with hostname"))
        mock_client_cls.return_value = client

        result = scan_link("https://dead-domain.example/affiliate", "link-8")
        self.assertEqual(result.issue_type, IssueType.DOMAIN_ERROR)
        self.assertEqual(result.severity, 3)

    @patch("common.scan_engine.httpx.Client")
    def test_timeout(self, mock_client_cls):
        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        client.get = MagicMock(side_effect=httpx.TimeoutException("Request timed out"))
        mock_client_cls.return_value = client

        result = scan_link("https://example.com/affiliate", "link-9")
        self.assertEqual(result.issue_type, IssueType.TIMEOUT)
        self.assertEqual(result.severity, 2)

    @patch("common.scan_engine.httpx.Client")
    def test_redirect_chain_captured(self, mock_client_cls):
        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        client.get = MagicMock(side_effect=[
            MockResponse(301, "https://example.com/redirect1", headers={"location": "/redirect2"}),
            MockResponse(302, "https://example.com/redirect2", headers={"location": "/final"}),
            MockResponse(200, "https://example.com/final"),
        ])
        mock_client_cls.return_value = client
        result = scan_link("https://example.com/affiliate", "link-10")
        self.assertEqual(len(result.redirect_chain), 3)
        self.assertEqual(result.redirect_chain[0].status_code, 301)
        self.assertEqual(result.redirect_chain[1].status_code, 302)
        self.assertEqual(result.redirect_chain[2].status_code, 200)

    @patch("common.scan_engine.httpx.Client")
    def test_blocked_ssrf_localhost(self, mock_client_cls):
        result = scan_link("http://127.0.0.1/admin", "link-11")
        self.assertEqual(result.issue_type, IssueType.SSRF_BLOCKED)
        self.assertEqual(result.severity, 3)
        self.assertIn("blocked", (result.error_message or "").lower())
        mock_client_cls.assert_not_called()

    @patch("common.scan_engine.httpx.Client")
    def test_blocked_ssrf_redirect_target(self, mock_client_cls):
        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        client.get = MagicMock(side_effect=[
            MockResponse(302, "https://example.com/redirect", headers={"location": "http://127.0.0.1/secret"}),
        ])
        mock_client_cls.return_value = client

        result = scan_link("https://example.com/affiliate", "link-12")
        self.assertEqual(result.issue_type, IssueType.SSRF_BLOCKED)
        self.assertEqual(result.severity, 3)


if __name__ == "__main__":
    unittest.main()
