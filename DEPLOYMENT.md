# Deployment Guide

## Production Stack
- `docker-compose.yml`
- `docker-compose.prod.yml`
- `vercel.json` for static frontend hosting
- `compose.ps1` for one-command dev/test/prod workflow

## Required Env
- Copy `.env.example` to `.env`
- Set production values for:
  - `DATABASE_URL`
  - `UPSTASH_REDIS_REST_URL`
  - `UPSTASH_REDIS_REST_TOKEN`
  - `REDIS_URL` if you still run Celery on Redis protocol
  - `CELERY_BROKER_URL`
  - `CELERY_RESULT_BACKEND`
  - `JWT_SECRET_KEY`
  - `API_KEY_SECRET`
  - `STRIPE_SECRET_KEY`
  - `STRIPE_WEBHOOK_SECRET`
  - `STRIPE_PRICING_TABLE_ID`
  - `STRIPE_PUBLISHABLE_KEY`
  - `SUPABASE_URL`
  - `SUPABASE_ANON_KEY`
  - `SUPABASE_JWT_SECRET` or `SUPABASE_JWKS_URL`
  - `DISCORD_WEBHOOK_URL`

## Run
```powershell
.\deploy-prod.ps1
```

## Dev / Test Workflow
```powershell
.\compose.ps1 -Mode dev
.\compose.ps1 -Mode test
.\compose.ps1 -Mode prod
```

## Frontend on Vercel
- Deploy the repo with `vercel.json`
- The dashboard reads `API Base URL` from the UI settings
- Set Supabase auth fields in the UI when `AUTH_MODE=supabase`

## Vercel + Supabase Quickstart
1. Create a Supabase project and copy `SUPABASE_URL`, `SUPABASE_ANON_KEY`, and `SUPABASE_JWKS_URL` or `SUPABASE_JWT_SECRET`
2. Set `AUTH_MODE=supabase` in backend env
3. Deploy the frontend to Vercel with this repo root
4. Open the dashboard, save `API Base URL`, then add Supabase auth values once
5. Use Supabase sign-in/up from the dashboard; local `/auth/login` and `/auth/register` are disabled in supabase mode

## Alerts
- Discord is the primary alert channel via `DISCORD_WEBHOOK_URL`
- Telegram code is left on hold and not invoked by default

## Billing Note
- Free is always available
- Paid plans are selected through Stripe Pricing Table embed
- Dashboard reads the table config from `/payments/pricing-table`

## Compose Flow
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml config
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

## Stop
```powershell
.\deploy-prod.ps1 -Down
```

## Notes
- API serves `/healthz`, `/livez`, `/readyz`, and `/metrics`
- Worker and API run with env-driven limits
- Use a managed database and Redis in real production
