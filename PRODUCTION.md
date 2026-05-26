# Phase 1 Setup

This project is currently prepared for:

- Meta OAuth
- GPT OAuth
- Tenant portal
- Admin dashboard
- Multi-tenant Meta app storage

## Required env vars

- `ENVIRONMENT=production`
- `PUBLIC_BASE_URL`
- `SESSION_SECRET`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `GPT_OAUTH_CLIENT_ID`
- `GPT_OAUTH_CLIENT_SECRET`
- `ADMIN_EMAIL`
- `ADMIN_PASSWORD`
- `ALLOW_ORIGINS` with your exact frontend/domain origins, not `*`

Optional:

- `ADMIN_API_KEY`
- `META_APP_ID`
- `META_APP_SECRET`
- `META_OAUTH_REDIRECT_URI`
- `META_TEST_ACCESS_TOKEN` for temporary testing only; do not use it for multi-client production.
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_OAUTH_REDIRECT_URI`
- `GOOGLE_OAUTH_SCOPES`

## Required SQL

Run:

- [supabase/multi_tenant_schema.sql](C:\Users\AcTivE\Desktop\manus_meta_server\supabase\multi_tenant_schema.sql)

## Phase 1 validation

1. Open `/portal/admin`
2. Login as admin
3. Add a client email
4. Open the client portal URL
5. Save Meta App credentials
6. Connect Meta
7. Verify `/accounts`, `/campaigns`, `/ads`, `/insights`

No intelligence layer should be tested before Phase 1 passes end-to-end.
