# mvp/tests/test_integration.py
"""Integration-ish tests for the worker task flow using mocked DB."""
from __future__ import annotations
import unittest
from unittest.mock import patch, MagicMock
from uuid import UUID

from worker.tasks import scan_project
from common.scan_engine import IssueType


class TestScanProjectTask(unittest.TestCase):
    @patch("worker.tasks.SessionLocal")
    @patch("worker.tasks.get_links_by_project")
    @patch("worker.tasks.scan_link")
    @patch("worker.tasks.upsert_issue")
    @patch("worker.tasks.create_issue_event")
    @patch("worker.tasks.get_open_issues_by_project")
    def test_scan_creates_issues_and_events(
        self,
        mock_get_open,
        mock_create_event,
        mock_upsert_issue,
        mock_scan_link,
        mock_get_links,
        mock_session_local,
    ):
        """Simulate a scan where one link has a 404 issue and one is healthy."""
        # Setup DB session mock
        mock_session = MagicMock()
        mock_session_local.return_value = mock_session
        mock_get_open.return_value = []

        # Two links
        link_404 = {
            "link_id": UUID("11111111-1111-1111-1111-111111111111"),
            "tenant_id": UUID("22222222-2222-2222-2222-222222222222"),
            "project_id": UUID("33333333-3333-3333-3333-333333333333"),
            "merchant_rule_id": UUID("44444444-4444-4444-4444-444444444444"),
            "original_url": "https://example.com/broken",
            "merchant_name": "Demo",
            "required_tracking_keys": [],
        }
        link_ok = {
            "link_id": UUID("55555555-5555-5555-5555-555555555555"),
            "tenant_id": UUID("22222222-2222-2222-2222-222222222222"),
            "project_id": UUID("33333333-3333-3333-3333-333333333333"),
            "merchant_rule_id": UUID("44444444-4444-4444-4444-444444444444"),
            "original_url": "https://example.com/ok",
            "merchant_name": "Demo",
            "required_tracking_keys": [],
        }
        mock_get_links.return_value = [link_404, link_ok]

        # Scan results
        result_404 = MagicMock()
        result_404.issue_type = IssueType.NOT_FOUND
        result_404.severity = 3
        result_404.original_url = "https://example.com/broken"
        result_404.final_url = None
        result_404.http_status = 404
        result_404.redirect_chain = []
        result_404.missing_params = []
        result_404.error_message = "HTTP 404"

        result_ok = MagicMock()
        result_ok.issue_type = None
        result_ok.severity = 0
        result_ok.original_url = "https://example.com/ok"
        result_ok.final_url = "https://example.com/ok"
        result_ok.http_status = 200
        result_ok.redirect_chain = []
        result_ok.missing_params = []
        result_ok.error_message = None

        mock_scan_link.side_effect = [result_404, result_ok]
        mock_upsert_issue.return_value = True  # new issue inserted

        # Mock the issue ID lookup after upsert
        with patch("sqlalchemy.orm.Session.execute") as mock_execute:
            mock_execute.return_value.fetchone.return_value = (UUID("66666666-6666-6666-6666-666666666666"),)
            # Run the task
            res = scan_project.run(
                scan_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                project_id="33333333-3333-3333-3333-333333333333",
            )

        # Assertions
        self.assertEqual(res["scanned"], 2)
        self.assertEqual(res["issues_created"], 1)
        self.assertEqual(res["issues_resolved"], 0)
        mock_upsert_issue.assert_called_once()
        mock_create_event.assert_called_once()

    @patch("worker.tasks.SessionLocal")
    @patch("worker.tasks.get_links_by_project")
    @patch("worker.tasks.scan_link")
    @patch("worker.tasks.upsert_issue")
    @patch("worker.tasks.create_issue_event")
    @patch("worker.tasks.get_open_issues_by_project")
    def test_auto_resolve_when_issue_gone(
        self,
        mock_get_open,
        mock_create_event,
        mock_upsert_issue,
        mock_scan_link,
        mock_get_links,
        mock_session_local,
    ):
        """If a link was previously broken but is now OK, the open issue should be resolved."""
        mock_session = MagicMock()
        mock_session_local.return_value = mock_session

        # One previously open issue
        prev_issue = {
            "id": UUID("77777777-7777-7777-7777-777777777777"),
            "tenant_id": UUID("22222222-2222-2222-2222-222222222222"),
            "project_id": UUID("33333333-3333-3333-3333-333333333333"),
            "link_id": UUID("11111111-1111-1111-1111-111111111111"),
            "issue_type": IssueType.NOT_FOUND,
        }
        mock_get_open.return_value = [prev_issue]

        link = {
            "link_id": UUID("11111111-1111-1111-1111-111111111111"),
            "tenant_id": UUID("22222222-2222-2222-2222-222222222222"),
            "project_id": UUID("33333333-3333-3333-3333-333333333333"),
            "merchant_rule_id": UUID("44444444-4444-4444-4444-444444444444"),
            "original_url": "https://example.com/broken",
            "merchant_name": "Demo",
            "required_tracking_keys": [],
        }
        mock_get_links.return_value = [link]

        # Now the link is healthy
        result_ok = MagicMock()
        result_ok.issue_type = None
        result_ok.severity = 0
        result_ok.original_url = "https://example.com/broken"
        result_ok.final_url = "https://example.com/broken"
        result_ok.http_status = 200
        result_ok.redirect_chain = []
        result_ok.missing_params = []
        result_ok.error_message = None
        mock_scan_link.return_value = result_ok
        mock_upsert_issue.return_value = False

        with patch("worker.tasks.resolve_issue") as mock_resolve:
            res = scan_project.run(
                scan_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                project_id="33333333-3333-3333-3333-333333333333",
            )

        self.assertEqual(res["scanned"], 1)
        self.assertEqual(res["issues_created"], 0)
        self.assertEqual(res["issues_resolved"], 1)
        mock_resolve.assert_called_once()

    @patch("worker.tasks.SessionLocal")
    @patch("worker.tasks.get_links_by_project")
    @patch("worker.tasks.scan_link")
    @patch("worker.tasks.upsert_issue")
    @patch("worker.tasks.create_issue_event")
    @patch("worker.tasks.get_open_issues_by_project")
    def test_variant_scans_aggregate_single_issue(
        self,
        mock_get_open,
        mock_create_event,
        mock_upsert_issue,
        mock_scan_link,
        mock_get_links,
        mock_session_local,
    ):
        """Multiple variants can scan the same link and still produce one issue record."""
        mock_session = MagicMock()
        mock_session_local.return_value = mock_session
        mock_get_open.return_value = []

        link = {
            "link_id": UUID("11111111-1111-1111-1111-111111111111"),
            "tenant_id": UUID("22222222-2222-2222-2222-222222222222"),
            "project_id": UUID("33333333-3333-3333-3333-333333333333"),
            "merchant_rule_id": UUID("44444444-4444-4444-4444-444444444444"),
            "original_url": "https://example.com/broken",
            "merchant_name": "Demo",
            "required_tracking_keys": [],
        }
        mock_get_links.return_value = [link]

        result_desktop = MagicMock()
        result_desktop.issue_type = IssueType.NOT_FOUND
        result_desktop.severity = 3
        result_desktop.original_url = link["original_url"]
        result_desktop.final_url = None
        result_desktop.http_status = 404
        result_desktop.redirect_chain = []
        result_desktop.missing_params = []
        result_desktop.error_message = "HTTP 404"
        result_desktop.variant_meta = {"name": "desktop"}

        result_mobile = MagicMock()
        result_mobile.issue_type = IssueType.NOT_FOUND
        result_mobile.severity = 3
        result_mobile.original_url = link["original_url"]
        result_mobile.final_url = None
        result_mobile.http_status = 404
        result_mobile.redirect_chain = []
        result_mobile.missing_params = []
        result_mobile.error_message = "HTTP 404"
        result_mobile.variant_meta = {"name": "mobile"}

        mock_scan_link.side_effect = [result_desktop, result_mobile]
        mock_upsert_issue.return_value = True

        with patch("sqlalchemy.orm.Session.execute") as mock_execute:
            mock_execute.return_value.fetchone.return_value = (UUID("66666666-6666-6666-6666-666666666666"),)
            res = scan_project.run(
                scan_id="cccccccc-cccc-cccc-cccc-cccccccccccc",
                project_id="33333333-3333-3333-3333-333333333333",
                scan_variants=[
                    {"name": "desktop"},
                    {"name": "mobile"},
                ],
            )

        self.assertEqual(res["scanned"], 1)
        self.assertEqual(mock_scan_link.call_count, 2)
        self.assertEqual(res["issues_created"], 1)
        mock_create_event.assert_called_once()


if __name__ == "__main__":
    unittest.main()
