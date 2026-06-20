# Affiliate Tracking Integrity Monitoring

MVP for monitoring affiliate link health, redirect behavior, and tracking parameter loss.

## Overview
- Multi-tenant FastAPI app with Celery workers, PostgreSQL, Redis, and Nginx
- Tracks links per project, scans them, and creates issues when integrity breaks

## Core Features
- Register/login users and tenants
- Create projects, merchant rules, and import links
- Start scans and view scan history
- Detect 404, redirect loop, timeout, SSL/domain errors, and tracking loss
- List, export, and resolve issues
- Send email and Telegram alerts

## Main Modules
- `api/` FastAPI routes, auth, payments, scan triggers
- `worker/` Celery scan execution and issue lifecycle updates
- `common/` shared scan engine, repositories, auth, and alerts
- `db/` schema and seed SQL
- `frontend/` simple dashboard shell

## Run
```bash
.\compose.ps1 -Mode dev
.\compose.ps1 -Mode test
```

## Production
```bash
.\compose.ps1 -Mode prod
```

## Endpoints
- `/auth`
- `/auth/config`
- `/projects`
- `/scans`
- `/issues`
- `/payments`
