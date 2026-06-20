# Architecture

## System Layout
- `FastAPI` handles HTTP API and serves the dashboard
- `Celery` runs async scan jobs
- `Redis` is the broker/result backend
- `PostgreSQL` stores tenants, projects, links, scans, issues, and events
- `Nginx` fronts the API

## Data Flow
1. User registers or logs in
2. API validates tenant access and stores project/link configuration
3. Scan request queues a Celery job
4. Worker loads project links and scans each URL
5. Scan results are upserted into `issues`
6. New issues create `issue_events` and trigger alerts
7. API exposes list/detail/export/resolve actions

## Key Components
- `api/main.py` routes and app bootstrap
- `api/routers/*` endpoint groups for auth, tenants, projects, scans, issues, payments
- `common/scan_engine.py` redirect and tracking-param checker
- `common/repositories.py` shared DB operations
- `worker/tasks.py` project scan orchestration
- `db/schema.sql` core tables and indexes

## Issue Model
- Issue types: `404`, `redirect_loop`, `tracking_param_lost`, `ssl_error`, `domain_error`, `timeout`, `other`
- Evidence stores redirect chain, final URL, HTTP status, missing params, and error message
