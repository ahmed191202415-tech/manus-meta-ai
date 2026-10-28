"""MCP tool adapters for existing application workflows."""
from app.schemas.meta_requests import ReadOnlyMetaQueryRequest
from app.mcp_actions import require_write
from app.schemas.gpt_tool_requests import (
    GA4ToolRequest, MetaTrackingToolRequest, WebsiteToolRequest,
    JourneyToolRequest, ClarityToolRequest,
)


def register_tools(mcp, post):
    """Expose validated service operations without duplicating their logic."""

    @mcp.tool()
    async def list_supported_services() -> dict:
        """List service families supported by the MCP adapter."""
        return {"services": [
            "meta_ads", "facebook_pages", "comments", "automation",
            "tracking", "ga4", "clarity", "customer_journey", "reports", "dashboards"
        ]}

    @mcp.tool()
    async def meta_graph_read(path: str, params: dict | None = None, page_id: str = "") -> dict:
        """Read campaigns, ad sets, ads, creatives, Pages, Instagram,
        comments, insights, audiences and Meta Graph resources.
        When working with a Facebook Page specify its page_id.
        """
        values = params or {}
        fields = str(values.get("fields") or "").lower()
        if any(secret in fields for secret in ("access_token", "app_secret", "client_secret")):
            raise ValueError("Credential fields cannot be returned over MCP")
        body = ReadOnlyMetaQueryRequest.model_validate({
            "path": path, "params": values, "page_id": page_id or None,
        })
        return await post("/meta/query", body.model_dump(exclude_none=True))

    @mcp.tool()
    async def meta_tracking(action: str, payload: dict | None = None) -> dict:
        """Retrieve Meta Pixel events, lead forms, leads, and custom conversions.
        Actions: list_pixels, received_pixel_events, custom_conversions,
        diagnose_lead_access, lead_forms, form_leads.
        """
        body = MetaTrackingToolRequest.model_validate({
            "action": action, "payload": payload or {},
        })
        return await post("/tools/meta_tracking", body.model_dump(exclude_none=True))

    @mcp.tool()
    async def google_analytics(action: str, payload: dict | None = None,
                               confirmed: bool = False) -> dict:
        """GA4 properties, standard/custom reports, events, realtime, funnels,
        sources and devices. select_property changes the saved selection.
        """
        if action == "select_property":
            require_write(confirmed)
        body = GA4ToolRequest.model_validate({"action": action, "payload": payload or {}})
        return await post("/tools/ga4", body.model_dump(exclude_none=True))

    @mcp.tool()
    async def website_intelligence(action: str, payload: dict | None = None) -> dict:
        """Website tracking audit, landing page, traffic, device and conversion analysis."""
        body = WebsiteToolRequest.model_validate({"action": action, "payload": payload or {}})
        return await post("/tools/website", body.model_dump(exclude_none=True))

    @mcp.tool()
    async def customer_journey(action: str, payload: dict | None = None) -> dict:
        """Meta-to-GA4 journey, funnel, attribution, tracking and UTM analysis."""
        body = JourneyToolRequest.model_validate({"action": action, "payload": payload or {}})
        return await post("/tools/journey", body.model_dump(exclude_none=True))

    @mcp.tool()
    async def clarity_analysis(action: str, payload: dict | None = None) -> dict:
        """Microsoft Clarity summary, pages and behavior audit."""
        body = ClarityToolRequest.model_validate({"action": action, "payload": payload or {}})
        return await post("/tools/clarity", body.model_dump(exclude_none=True))
