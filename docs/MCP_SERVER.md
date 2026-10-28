# Super Ad Analysis — MCP integration

This project now exposes its existing FastAPI business logic through MCP
**Streamable HTTP**, without removing the REST API.

## URL and transport

The FastAPI application mounts the MCP subapplication at `/mcp`, and the
internal transport route is `/`. Connect using the **trailing slash**:

```
https://YOUR-RAILWAY-HOST/mcp/
```

Use the original application's bearer credentials in the MCP client's
`Authorization: Bearer ...` header. The MCP adapter forwards this bearer
header to the corresponding in-process FastAPI operation. Do not use a GitHub
token. Do not put credentials in the URL. The selected tenant's Meta, Google
and Clarity permissions determine the data that is actually available.

`PUBLIC_BASE_URL` must match the public Railway service origin for MCP
Host/Origin security validation.

## Tool inventory

- Discover ad accounts, campaigns, ad sets, ads, Pages, posts and comments
- Read Meta Graph and run Meta Insights and campaign diagnostics
- Create campaigns, ad sets, ads, creatives, custom audiences and Pixels
- Update/pause/resume existing assets using validated Meta write operations
- Publish/schedule Page posts, publicly reply to comments, hide/unhide comments
- Read and manage comment automation rules, Page subscription, ad-scoped rules,
  verified post aliases, webhook diagnostics and execution logs
- Read Pixel events, custom conversions, lead forms and form leads
- GA4 reports, custom reports, property selection, realtime and funnels
- Microsoft Clarity, website conversion/landing-page and customer-journey audits
- Export PDF, Excel, PPTX, DOCX and HTML reports
- Manage stored dashboards and arbitrary tenant datasets
- Universal dashboard runtime: capabilities, validate, preview, execute and
  confirmed publish_section operations

The MCP adapter reuses the exact existing route handlers rather than
reimplementing Meta APIs. Availability depends on Meta/GA4/Clarity permissions
and configured tenant connections.

## Writes and safeguards

**Read operations work with existing API credentials.** Remote MCP writes are
disabled by default. To allow edits, add this to Railway:

```
MCP_WRITES_ENABLED=true
```

Every write tool also requires `confirmed=true` after the connecting client
has shown the exact target, proposed values, likely external effects and
received human approval. This boolean alone is not cryptographic proof of
human confirmation; configure your client to enforce approval, and restrict
who can access the MCP endpoint. Never allow unreviewed autonomous spending,
posting, deleting or mass replying.

Meta campaigns, Ad Sets and Ads default to PAUSED when creating via the typed
endpoints unless a different status is explicitly supplied. Financial edits
and deletions should be separately confirmed.

**Read-only production rollout is recommended first.** Enable write support
only after your tenant authentication and scopes have been verified.

## Railway deployment

No additional service process is required. Keep:

```
uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

Merge after tests pass and deploy the main branch. Verify both:

- `/docs` — existing REST API is available
- `/mcp/` — MCP initialize, tools/list and authenticated tools/call work

Run `python -m pytest -q tests/test_mcp_adapter.py tests/test_mcp_comprehensive.py`
plus the existing app regression tests. The GitHub workflow
`.github/workflows/mcp-validation.yml` also runs these checks.

## Limitations

- The integration has not been deployed to your Railway service by a commit
  alone. Deployment and live Meta Page permissions must be tested separately.
- OAuth account linking still happens via the existing portal / OAuth routes.
- The MCP transport currently expects a caller-supplied bearer credential.
  Some MCP clients require a standards-based OAuth authorization server; such
  clients may need an additional OAuth compatibility layer.
- Background Meta webhook subscriptions rely on the existing public webhook
  route and correct Meta App configuration, not just the MCP endpoint.
