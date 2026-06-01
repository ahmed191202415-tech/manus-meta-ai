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
- `META_WEBHOOK_VERIFY_TOKEN` as a long random value for Meta webhook verification
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
- `META_WEBHOOK_VERIFY_TOKEN` for Meta webhook verification. Use a long random value.
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

## Facebook comment automations

To enable automatic public replies and Messenger private replies:

1. Run the latest `supabase/multi_tenant_schema.sql`.
2. Add `META_WEBHOOK_VERIFY_TOKEN` to Railway.
3. In the Meta app Webhooks product, subscribe to the Page object and its `feed` field.
4. Set the callback URL to `https://your-domain.com/webhooks/meta`.
5. Use the same `META_WEBHOOK_VERIFY_TOKEN` value as the webhook verify token.
6. Reconnect Meta so the granted scopes include `pages_messaging`.
   The server also requests `pages_manage_metadata` so it can subscribe the selected Page to webhook events.

ChatGPT uses `POST /comment_automations/manage` to list pages and posts, subscribe a Page,
create a per-post rule, inspect recent execution logs, disable a rule, or delete it.
