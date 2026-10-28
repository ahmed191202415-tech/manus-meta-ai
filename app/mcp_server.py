"""Read-only MCP adapter for the existing advertising intelligence API.

Connect at /mcp with Streamable HTTP. An Authorization: Bearer header is
forwarded to the existing API authentication resolver. No Meta write tools
are exposed by this adapter.
"""
from urllib.parse import urlparse

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.lowlevel.server import request_ctx
from mcp.server.transport_security import TransportSecuritySettings

from app.config import PUBLIC_BASE_URL
from app.schemas.analysis_requests import AnalysisRunRequest
from app.schemas.meta_requests import ReadOnlyMetaQueryRequest, SmartMetaInsightsRequest
from app.schemas.gpt_tool_requests import IntentToolRequest


def _transport_security():
    allowed_hosts = ["localhost:*", "127.0.0.1:*"]
    allowed_origins = ["http://localhost:*", "http://127.0.0.1:*"]
    if PUBLIC_BASE_URL:
        parsed = urlparse(PUBLIC_BASE_URL)
        if parsed.netloc:
            allowed_hosts.append(parsed.netloc)
            allowed_origins.append(f"{parsed.scheme}://{parsed.netloc}")
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )


mcp = FastMCP("Super Ad Analysis", streamable_http_path="/", stateless_http=True, json_response=True, transport_security=_transport_security(), instructions=(
    "Read-only advertising analytics. Use discover_accounts to discover Meta accounts; "
    "use meta_insights for campaign, ad set, or ad reporting; use run_analysis "
    "for diagnostics and recommendations. Never claim data was fetched if a tool "
    "returned an error. Auth uses the caller's existing API bearer token."
))


_REDACTED_KEYS = {"access_token", "page_access_token", "meta_access_token", "refresh_token", "client_secret", "app_secret", "api_key", "authorization", "password"}


def _redact_secrets(data):
    if isinstance(data, dict):
        return {key: ("[REDACTED]" if str(key).casefold() in _REDACTED_KEYS else _redact_secrets(value)) for key, value in data.items()}
    if isinstance(data, list):
        return [_redact_secrets(item) for item in data]
    return data


async def _post(path: str, payload: dict) -> dict:
    request = request_ctx.get().request
    if request is None:
        raise ValueError('MCP requires an HTTP request context')
    authorization = request.headers.get("authorization", "")
    if not authorization.lower().startswith("bearer ") or not authorization[7:].strip():
        raise ValueError("Authorization: Bearer <existing API token> is required")
    # Local ASGI calls reuse authorization and validation without exposing an
    # internal HTTP service or duplicating analytics logic.
    from app.main import app
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://internal",
        timeout=120.0,
    ) as client:
        response = await client.post(
            path,
            json=payload,
            headers={"authorization": authorization},
        )
    if response.status_code >= 400:
        raise ValueError(f"API {response.status_code}: {response.text[:1500]}")
    return _redact_secrets(response.json())


@mcp.tool()
async def discover_accounts() -> dict:
    """List authorized Meta advertising accounts and their IDs."""
    return await _post("/meta/query", {
        "path": "me/adaccounts",
        "params": {"fields": "id,name,account_id,account_status,currency,timezone_name", "limit": 100},
    })


@mcp.tool()
async def meta_insights(
    account_id: str = "",
    account_name: str = "",
    campaign_id: str = "",
    adset_id: str = "",
    ad_id: str = "",
    level: str = "campaign",
    date_preset: str = "last_7d",
    limit: int = 50,
) -> dict:
    """Read Meta ad performance using the existing smart fallback strategy."""
    payload = {
        "account_id": account_id or None,
        "account_name": account_name or None,
        "campaign_id": campaign_id or None,
        "adset_id": adset_id or None,
        "ad_id": ad_id or None,
        "level": level,
        "date_preset": date_preset,
        "limit": max(1, min(limit, 100)),
    }
    return await _post("/meta/smart_insights", SmartMetaInsightsRequest.model_validate(payload).model_dump(exclude_none=True))


@mcp.tool()
async def run_analysis(
    account_id: str,
    analysis_type: str = "executive_report",
    level: str = "campaign",
    date_preset: str = "last_7d",
    since: str = "",
    until: str = "",
    top_n: int = 10,
) -> dict:
    """Run existing AI diagnostics, KPI summaries, comparisons, or recommendations.

    Examples of analysis_type: executive_report, summary_kpis, ranking,
    intelligence_diagnostics, anomaly_scan, period_comparison, budget_reallocation.
    """
    payload = AnalysisRunRequest.model_validate({
        "account_id": account_id,
        "analysis_type": analysis_type,
        "level": level,
        "date_preset": date_preset if not (since and until) else None,
        "since": since or None,
        "until": until or None,
        "top_n": max(1, min(top_n, 50)),
    })
    return await _post("/analysis/run", payload.model_dump(exclude_none=True))


@mcp.tool()
async def route_analysis_request(request: str, meta_account_id: str = "") -> dict:
    """Map an Arabic or English marketing question to supported API operations."""
    body = IntentToolRequest.model_validate({
        "request": request,
        "meta_account_id": meta_account_id or None,
    })
    return await _post("/tools/intent", body.model_dump(exclude_none=True))


from app.mcp_capabilities import register_tools

register_tools(mcp, _post)
from app.mcp_actions import register_action_tools
register_action_tools(mcp, _post)
from app.mcp_reporting import register_reporting_tools
register_reporting_tools(mcp, _post)
from app.mcp_discovery import register_discovery_tools
register_discovery_tools(mcp, _post)
mcp_asgi_app = mcp.streamable_http_app()
