# TODO — MVP: Affiliate Tracking Integrity Monitoring (Revenue Protection)

> Last updated: after Priority-1 implementation pass (Worker Scan + Issues API)

## Step 1: Repo scaffolding
- [x] สร้างโฟลเดอร์ `mvp/`
- [x] เลือก stack และกำหนดโครงสร้างไฟล์เริ่มต้น
- [x] สร้าง `README_MVP.md` (วิธีรัน)

## Step 2: Database schema (Postgres)
- [x] ออกแบบตาราง multi-tenant: tenants, projects, links, merchant_rules, scans, issues, issue_events
- [x] สร้าง migration (หรือ SQL init) สำหรับ local dev (`schema.sql` + `seed.sql` + `init.sql`)

## Step 3: API (FastAPI) — minimal but functional
- [x] Auth: API key ต่อ tenant (อย่างง่าย — `X-API-Key` = tenant UUID)
- [x] Endpoints: create tenant, create project, import links (JSON), set merchant rule template
- [x] Start scan job (`POST /scans/start` → Celery enqueue)
- [x] Query issues (`GET /issues`, `GET /issues/{id}`, `PATCH /issues/{id}` resolve)

## Step 4: Worker + job queue
- [x] Scheduler/worker โหมด MVP: manual trigger (`POST /scans/start`) + Celery worker
- [x] HTTP fetcher: follow redirects with limit (max 10 hops) + capture redirect chain
- [x] Rule engine: classify issues (`404`, `redirect_loop`, `tracking_param_lost`, `ssl_error`, `domain_error`, `timeout`, `other`)
- [x] Auto-resolve: open issues that are no longer detected during a scan get resolved automatically

## Step 5: Alerting (MVP-lite)
- [x] Email alert: ส่งเฉพาะ issue created (SMTP configurable ผ่าน env vars, skip ถ้าไม่ได้ตั้งค่า)
- [x] Telegram alert: ส่งข้อความผ่าน Bot API เมื่อ issue created (configurable ผ่าน env vars)

## Step 6: Frontend / Dashboard (ขั้นต่ำ)
- [x] Simple UI: project list + issues list + issue detail (redirect chain + missing params) — SPA แบบ vanilla JS ที่ `/`
- [x] Export CSV (`GET /issues/export.csv` + ปุ่มใน dashboard)

## Step 7: Freemium + usage limits (MVP gating)
- [x] จำกัดจำนวน links ตาม plan ใน backend (`free`=100, `pro`=1000, `enterprise`=10000)
- [x] จำกัด scan frequency (`free`=1h, `pro`=15m, `enterprise`=1m)

## Step 8: Security hardening
- [x] API Key hashing: ใช้ HMAC-SHA256 แทน UUID ตรง ๆ (`common/auth_utils.py`)
- [x] Project ownership validation: ทุก endpoint ตรวจสอบ tenant เป็นเจ้าของ project จริง
- [x] Create tenant ไม่ต้อง auth → คืน raw API key ที่แสดงครั้งเดียว

## Step 9: Final packaging
- [x] Docker compose สำหรับ local: api + worker + postgres + redis(optional)
- [x] เอกสารการ deploy เบื้องต้น (รัน `docker compose up --build` ได้เลย)

