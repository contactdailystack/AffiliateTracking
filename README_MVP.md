# MVP - Affiliate Tracking Integrity Monitoring

![CI](https://img.shields.io/badge/CI-build%20%2F%20test%20%2F%20lint-brightgreen)
![Python](https://img.shields.io/badge/Python-3.12-blue)
![Docker](https://img.shields.io/badge/Docker-ready-0db7ed)

## Goal
- Monitor affiliate tracking integrity
- Follow redirect chains and classify revenue-risk issues
- Create issues and send alerts

## Tech Stack
- Backend: Python + FastAPI
- Worker: Celery + Redis
- DB: PostgreSQL
- Queue: Redis broker

## Recommended Free Stack
- `Supabase` for DB and auth
- `FastAPI` for backend API
- `Vercel` for frontend hosting
- `Resend` for email alerts
- `Redis + Celery` for worker queue, with Upstash REST for API rate limiting
- `Discord` for issue alerts; Telegram is on hold

## Plans
- Free: always available
- Pro: $10/month
- Pro+: $20/month
- Paid plan selection uses a Stripe Pricing Table

## Frontend Deploy
- Static-ready on Vercel via `vercel.json`
- Set `API Base URL` and optional Supabase auth values in the dashboard settings

## Local Development
### Prerequisites
- Docker Desktop

### Run Dev
```bash
.\compose.ps1 -Mode dev
```

### Run Dev / Test Workflow
```powershell
.\compose.ps1 -Mode dev
.\compose.ps1 -Mode test
```

### Run Production Compose
```powershell
.\deploy-prod.ps1
```

### Production Guide
- See [DEPLOYMENT.md](DEPLOYMENT.md)

### Team Standards
```bash
pip install pre-commit
pre-commit install
```

## API
- `http://localhost:8000`
- `http://localhost:8000/docs`

## Project Structure
- `mvp/api/` FastAPI app
- `mvp/worker/` Celery worker
- `mvp/common/` shared modules
- `mvp/db/` SQL schema and seed
- `mvp/tests/` tests
- `wordpress-plugin/` optional WordPress sync plugin

## MVP Milestones
1. Seed data and run scan
2. Issue detail with redirect proof
3. Email alert on issue creation

## Notes
- Limit false positives with redirect hop caps and deterministic rules
