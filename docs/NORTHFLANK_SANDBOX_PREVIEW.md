# Northflank isolated sandbox preview

Source: `experiment/vercel-fastapi-preview` at commit `787a83d`.
This branch is **not** a replacement for production. No production DNS, OAuth callbacks, webhooks, database or credentials are changed.

## Known compatibility findings

- Python 3.12 FastAPI application; entrypoint: `app.main:app`.
- Heavy dependencies: `google-ads==35.0.0`, `pandas`, `numpy`, `scipy`, `scikit-learn`, plus exports libraries.
- The application eagerly imports the router registry; benchmark cold-start duration and memory.
- `/health` responds without querying Supabase. Do not expose `/health/auth_connection_probe` publicly as it provides diagnostics.
- `PUBLIC_BASE_URL` influences OAuth callbacks and OpenAPI servers; leave unconfigured in the isolated test.
- Existing app expects persistent state in Supabase; never copy production service-role credentials into Sandbox.
- Exports are ephemeral in `/tmp/manus-meta/exports`. Persist only in a separately approved environment.

## Northflank service setup

1. Create a **Developer Sandbox** project in Northflank.
2. Connect GitHub repo `ahmed191202415-tech/manus-meta-ai`.
3. Create **Combined service**, selecting only branch `experiment/northflank-sandbox-preview`.
4. Build method: **Dockerfile**. Dockerfile path: `/Dockerfile.northflank`, context: repository root.
5. Start command: use the image's default CMD. Exactly **one** instance; begin with Sandbox's default compute.
6. Network: HTTP port `8000`, expose initially as **private** while verifying the build and logs. Do not attach `app.allingpt.online`.
7. Set process startup readiness/liveness HTTP path `/health` on port 8000, with sufficient initial delay for heavy imports.
8. Variables for smoke testing only: `ENVIRONMENT=development`, `EXPORT_DIR=/tmp/manus-meta/exports`, `LOG_LEVEL=INFO`. Do not provide OAuth client secrets, production Supabase keys or Meta tokens.
9. Only once a separate demo auth boundary and sandbox database are prepared should you expose an HTTPS preview endpoint for integration testing.
10. Disable automatic deploys from production branches and avoid registering this URL with ChatGPT or Meta/Google OAuth.

## Smoke tests

Run privately within the service network, or via Northflank console, before public exposure:

```bash
python -c "from app.main import app; print(app.title, app.version)"
curl -fsS http://127.0.0.1:8000/health
```

Expected `/health`: JSON with `ok: true`. This tests startup only, **not** Google Ads, Meta or Supabase functionality.

Additional read-only checks (after disposable test credentials and a test database are provided):

- Google Ads read-only account discovery; no campaign writes.
- Meta read-only account and campaign list.
- Supabase read-only tenant lookup in a separate test project.
- OAuth callback URL construction and redirect handling using a test app.
- PDF/DOCX/XLSX export paths with throwaway data.
- Memory and CPU telemetry after repeated requests and idle periods.

## Production cutover guardrails

Do not switch `app.allingpt.online`, change production OAuth registered redirect URIs, move production secrets, invoke write endpoints, or register production Meta Webhooks during this preview.

## Sandbox billing caveat

Northflank pricing lists Sandbox with up to $20/month of included resources and always-on services, but a separate billing documentation page says a payment method may be required. Confirm conditions and resource headroom in your dashboard before enabling. Sandbox is not recommended as a production SLA.
