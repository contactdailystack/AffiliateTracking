import logging
from typing import Any
from uuid import UUID

from celery import shared_task
from celery.exceptions import MaxRetriesExceededError
from sqlalchemy import text

from common.scan_engine import scan_link
from common.repositories import (
    create_issue_event,
    complete_scan_record,
    get_open_issues_by_project,
    get_links_by_project,
    resolve_issue,
    upsert_issue,
)
from common.email_alert import send_issue_alert
from common.discord_alert import send_discord_issue_alert
from .db import SessionLocal

logger = logging.getLogger(__name__)


def _default_scan_variants() -> list[dict[str, Any]]:
    return [{"name": "default"}]


def _normalize_variants(scan_variants: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    variants = scan_variants or _default_scan_variants()
    normalized: list[dict[str, Any]] = []
    for index, variant in enumerate(variants):
        item = dict(variant or {})
        item.setdefault("name", f"variant-{index + 1}")
        normalized.append(item)
    return normalized


def _issue_evidence(link: dict[str, Any], variant_results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "link_id": str(link["link_id"]),
        "original_url": link["original_url"],
        "variant_results": variant_results,
    }


@shared_task(name="mvp.worker.tasks.scan_project", bind=True, max_retries=3)
def scan_project(self, scan_id: str, project_id: str, scan_variants: list[dict[str, Any]] | None = None):
    """Scan every link in a project, classify issues, and update the DB."""
    sid = UUID(scan_id)
    pid = UUID(project_id)
    session = SessionLocal()
    variants = _normalize_variants(scan_variants)

    try:
        # 1. Load all links + their merchant rules for this project
        links = get_links_by_project(session, pid)
        if not links:
            logger.info("No links found for project_id=%s", project_id)
            complete_scan_record(session, sid, status="completed")
            return {"scanned": 0, "issues_created": 0, "issues_resolved": 0}

        # 2. Build set of currently open issues for auto-resolve logic
        open_issues = get_open_issues_by_project(session, pid)
        open_key_to_id = {
            (str(row["link_id"]), row["issue_type"]): str(row["id"])
            for row in open_issues
        }
        still_open: set = set()

        issues_created = 0
        issues_resolved = 0

        # 3. Scan each link across the requested variants
        for link in links:
            variant_results: list[dict[str, Any]] = []
            for variant in variants:
                result = scan_link(
                    original_url=link["original_url"],
                    link_id=str(link["link_id"]),
                    required_tracking_keys=link["required_tracking_keys"] or [],
                    scan_variant=variant,
                    max_redirects=10,
                    timeout=30.0,
                )
                variant_results.append(
                    {
                        "variant": variant.get("name", "default"),
                        "variant_meta": result.variant_meta,
                        "issue_type": result.issue_type,
                        "severity": result.severity,
                        "final_url": result.final_url,
                        "http_status": result.http_status,
                        "redirect_chain": [
                            {"url": hop.url, "status_code": hop.status_code}
                            for hop in result.redirect_chain
                        ],
                        "missing_params": result.missing_params,
                        "error_message": result.error_message,
                    }
                )

            issue_groups: dict[str, list[dict[str, Any]]] = {}
            for item in variant_results:
                if item["issue_type"]:
                    issue_groups.setdefault(item["issue_type"], []).append(item)

            for issue_type, matched_results in issue_groups.items():
                best_result = max(matched_results, key=lambda item: item["severity"])
                key = (str(link["link_id"]), issue_type)
                evidence = _issue_evidence(link, variant_results)
                evidence["matched_variant_results"] = matched_results

                was_inserted = upsert_issue(
                    session=session,
                    tenant_id=UUID(link["tenant_id"]),
                    project_id=UUID(link["project_id"]),
                    link_id=UUID(link["link_id"]),
                    merchant_rule_id=UUID(link["merchant_rule_id"]),
                    issue_type=issue_type,
                    severity=best_result["severity"],
                    evidence=evidence,
                )

                if was_inserted:
                    issues_created += 1
                    send_issue_alert(
                        issue_type=issue_type,
                        severity=best_result["severity"],
                        original_url=link["original_url"],
                        final_url=best_result["final_url"],
                        missing_params=best_result["missing_params"],
                        redirect_chain=best_result["redirect_chain"],
                        error_message=best_result["error_message"],
                    )
                    send_discord_issue_alert(
                        issue_type=issue_type,
                        severity=best_result["severity"],
                        original_url=link["original_url"],
                        final_url=best_result["final_url"],
                        missing_params=best_result["missing_params"],
                        error_message=best_result["error_message"],
                    )
                    row = session.execute(
                        text(
                            "SELECT id FROM issues WHERE tenant_id=:t AND project_id=:p AND link_id=:l AND issue_type=:it"
                        ),
                        {
                            "t": str(link["tenant_id"]),
                            "p": str(link["project_id"]),
                            "l": str(link["link_id"]),
                            "it": issue_type,
                        },
                    ).fetchone()
                    if row:
                        create_issue_event(
                            session=session,
                            tenant_id=UUID(link["tenant_id"]),
                            issue_id=UUID(str(row[0])),
                            event_type="created",
                            payload=evidence,
                        )
                else:
                    row = session.execute(
                        text(
                            "SELECT id FROM issues WHERE tenant_id=:t AND project_id=:p AND link_id=:l AND issue_type=:it"
                        ),
                        {
                            "t": str(link["tenant_id"]),
                            "p": str(link["project_id"]),
                            "l": str(link["link_id"]),
                            "it": issue_type,
                        },
                    ).fetchone()
                    if row:
                        create_issue_event(
                            session=session,
                            tenant_id=UUID(link["tenant_id"]),
                            issue_id=UUID(str(row[0])),
                            event_type="updated",
                            payload=evidence,
                        )

                still_open.add(key)

        # 4. Auto-resolve issues that were open before but no longer detected
        # Build a map issue_id -> tenant_id from the open_issues list
        issue_id_to_tenant = {str(row["id"]): str(row["tenant_id"]) for row in open_issues}
        for (link_id_str, issue_type_str), issue_id_str in open_key_to_id.items():
            if (link_id_str, issue_type_str) not in still_open:
                tenant_id_str = issue_id_to_tenant.get(issue_id_str)
                if not tenant_id_str:
                    continue
                resolve_issue(
                    session=session,
                    issue_id=UUID(issue_id_str),
                    evidence={"reason": "Auto-resolved: issue no longer detected during scan"},
                )
                create_issue_event(
                    session=session,
                    tenant_id=UUID(tenant_id_str),
                    issue_id=UUID(issue_id_str),
                    event_type="resolved",
                    payload={"reason": "Auto-resolved: issue no longer detected during scan"},
                )
                issues_resolved += 1

        complete_scan_record(session, sid, status="completed")
        return {
            "scanned": len(links),
            "issues_created": issues_created,
            "issues_resolved": issues_resolved,
        }

    except Exception as exc:
        logger.exception("Scan project failed for project_id=%s", project_id)
        try:
            raise self.retry(countdown=60, exc=exc)
        except MaxRetriesExceededError:
            complete_scan_record(session, sid, status="failed")
            raise
    finally:
        session.close()
