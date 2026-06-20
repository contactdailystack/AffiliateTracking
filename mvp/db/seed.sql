-- Minimal seed for local testing

INSERT INTO tenants (id, name, api_key_hash, plan)
VALUES ('11111111-1111-1111-1111-111111111111', 'demo', 'e01f425f74326c65d9069fb54a4b9ff96505a0a5c50d3fa3ba54d96de26fffce', 'free')
ON CONFLICT (id) DO UPDATE SET api_key_hash = EXCLUDED.api_key_hash, plan = EXCLUDED.plan;

INSERT INTO projects (id, tenant_id, name, scan_frequency_seconds)
VALUES ('22222222-2222-2222-2222-222222222222', '11111111-1111-1111-1111-111111111111', 'Demo Project', 86400)
ON CONFLICT DO NOTHING;

INSERT INTO merchant_rules (id, tenant_id, project_id, merchant_name, required_tracking_keys)
VALUES (
  '33333333-3333-3333-3333-333333333333',
  '11111111-1111-1111-1111-111111111111',
  '22222222-2222-2222-2222-222222222222',
  'Demo Merchant',
  '[{"key":"tag","required":true},{"key":"subid","required":false}]'::jsonb
)
ON CONFLICT DO NOTHING;

-- Demo user: email=demo@example.com, password=Demo1234!
INSERT INTO users (id, tenant_id, email, password_hash, full_name)
VALUES (
  '44444444-4444-4444-4444-444444444444',
  '11111111-1111-1111-1111-111111111111',
  'demo@example.com',
  '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.VTtYA.qGZvKG6',
  'Demo User'
)
ON CONFLICT (email) DO NOTHING;

-- Scan schedule for demo project
INSERT INTO scan_schedules (id, project_id, enabled)
VALUES ('55555555-5555-5555-5555-555555555555', '22222222-2222-2222-2222-222222222222', true)
ON CONFLICT DO NOTHING;

