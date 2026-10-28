# MCP Server (Streamable HTTP)

The FastAPI application also exposes a **read-only** MCP endpoint at `/mcp`.
It preserves all existing REST endpoints and runs on the existing Railway process.

## Connect

URL: `https://YOUR-RAILWAY-DOMAIN/mcp`

Transport: Streamable HTTP. Supply `Authorization: Bearer YOUR_EXISTING_API_TOKEN`
in the client's HTTP headers. Use an existing, scoped API token (not a GitHub
token). This adapter forwards the same header to the app's existing authentication
logic; its MCP tools never expose Meta write operations.

Supported tools: `discover_accounts`, `meta_insights`,
`run_analysis`, `route_analysis_request`.

## Railway

Set `PUBLIC_BASE_URL` to the exact public HTTPS origin of the Railway service
(e.g. `https://example.up.railway.app`). The MCP transport validates its Host
and Origin against this configured domain and localhost.

Existing `Procfile` remains valid; no separate worker is required.
MCP state is stateless across requests. Existing REST API documentation remains
available at `/docs`.

## Verify

Install requirements then run the existing Uvicorn command. Use an MCP client
with the URL above and Authorization header; check tools/list and run
discover_accounts with a valid account token. Invalid or missing tokens must
not return account data. Verify `/docs`, `/analysis/run`, and other REST
routes still work.

No Railway deployment is performed by GitHub commits alone. Review and merge
the pull request, deploy, and test the production URL before relying on MCP.
