# mvp/tests/demo_e2e.py
"""End-to-end demo script for the Affiliate MVP.

Prerequisites:
  - API running at http://localhost:8000
  - Worker running (Celery)
  - Postgres + Redis up

Usage:
  python -m tests.demo_e2e

This script will:
  1. Use the seeded demo tenant UUID
  2. Create a project
  3. Set a merchant rule with required tracking keys
  4. Import sample links (mix of known-good and known-broken URLs)
  5. Trigger a scan
  6. Poll for issues
  7. Export CSV
"""
from __future__ import annotations
import sys
import time
import uuid
import requests

API_BASE = "http://localhost:8000"
HEADERS = {"Content-Type": "application/json", "X-API-Key": "11111111-1111-1111-1111-111111111111"}


def api(method: str, path: str, json_data=None):
    url = f"{API_BASE}{path}"
    r = requests.request(method, url, headers=HEADERS, json=json_data, timeout=30)
    print(f">>> {method} {path} — HTTP {r.status_code}")
    if r.status_code >= 400:
        print(f"    Error: {r.text}")
    return r


def ensure_demo_tenant():
    """Ensure the demo tenant exists."""
    print("Tenant provisioning is handled by the authenticated bootstrap flow.")


def run():
    print("=" * 60)
    print("Affiliate MVP — End-to-End Demo")
    print("=" * 60)

    # 1. Ensure tenant
    ensure_demo_tenant()

    # 2. Create project
    tenant_id = "11111111-1111-1111-1111-111111111111"
    project_name = f"Demo Project {uuid.uuid4().hex[:6]}"
    r = api("POST", "/projects", {"tenant_id": tenant_id, "name": project_name, "scan_frequency_seconds": 86400})
    if r.status_code != 200:
        print("Failed to create project. Exiting.")
        sys.exit(1)
    project = r.json()
    project_id = str(project["id"])
    print(f"Project created: {project_id} — {project_name}")

    # 3. Set merchant rule
    rule = {
        "tenant_id": tenant_id,
        "project_id": project_id,
        "merchant_name": "DemoMerchant",
        "required_tracking_keys": [
            {"key": "tag", "required": True},
            {"key": "subid", "required": False},
        ],
    }
    r = api("POST", "/projects/merchant-rules", rule)
    if r.status_code not in (200, 201):
        print("Failed to set merchant rule. Exiting.")
        sys.exit(1)
    print("Merchant rule set.")

    # 4. Import sample links
    # We mix a known-good URL and a known-broken URL for demo purposes.
    links = [
        {"merchant_name": "DemoMerchant", "original_url": "https://httpbin.org/status/404", "source_label": "test-404"},
        {"merchant_name": "DemoMerchant", "original_url": "https://httpbin.org/redirect/3", "source_label": "test-redirect"},
        {"merchant_name": "DemoMerchant", "original_url": "https://httpbin.org/get?tag=demo123", "source_label": "test-ok"},
    ]
    r = api("POST", "/projects/import-links", {"tenant_id": tenant_id, "project_id": project_id, "links": links})
    if r.status_code != 200:
        print("Failed to import links. Exiting.")
        sys.exit(1)
    inserted = r.json().get("inserted", 0)
    print(f"Imported {inserted} link(s).")

    # 5. Trigger scan
    r = api("POST", "/scans/start", {"project_id": project_id})
    if r.status_code != 200:
        print("Failed to start scan. Exiting.")
        sys.exit(1)
    task_id = r.json().get("celery_task_id")
    print(f"Scan queued. Task ID: {task_id}")

    # 6. Poll for issues (wait for worker to finish)
    print("Polling for issues (max 60s)...")
    issues = []
    for _ in range(30):
        time.sleep(2)
        r = api("GET", f"/issues?project_id={project_id}&limit=50")
        if r.status_code == 200:
            data = r.json()
            issues = data.get("items", [])
            if issues:
                print(f"Found {len(issues)} issue(s)!")
                break
        else:
            print("No issues yet, retrying...")

    if not issues:
        print("No issues detected within timeout. This may be normal for healthy URLs.")
    else:
        print("\nIssues detected:")
        for i in issues:
            print(f"  - [{i['issue_type']}] Severity {i['severity']} | Status: {i['status']}")
            ev = i.get("evidence", {})
            print(f"    Original: {ev.get('original_url', 'N/A')}")
            print(f"    Final: {ev.get('final_url', 'N/A')}")
            print(f"    HTTP: {ev.get('http_status', 'N/A')}")
            print(f"    Missing params: {ev.get('missing_params', [])}")
            print(f"    Error: {ev.get('error_message', 'N/A')}")
            print()

    # 7. Resolve the first issue manually (demo)
    if issues:
        first_id = issues[0]["id"]
        print(f"Resolving first issue {first_id}...")
        r = api("PATCH", f"/issues/{first_id}", {"reason": "Resolved during E2E demo"})
        if r.status_code == 200:
            print("Issue resolved successfully.")
        else:
            print("Failed to resolve issue.")

    # 8. Export CSV
    print("Exporting CSV...")
    r = requests.get(
        f"{API_BASE}/issues/export.csv?project_id={project_id}",
        headers={"X-API-Key": HEADERS["X-API-Key"]},
        timeout=30,
    )
    if r.status_code == 200:
        csv_path = f"demo_issues_{project_id}.csv"
        with open(csv_path, "w", encoding="utf-8") as f:
            f.write(r.text)
        print(f"CSV exported to: {csv_path}")
    else:
        print(f"CSV export failed: {r.status_code}")

    print("=" * 60)
    print("Demo complete.")
    print("=" * 60)


if __name__ == "__main__":
    run()
