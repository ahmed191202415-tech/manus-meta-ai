"""Additional MCP adapters to existing validated service endpoints."""


def register_tools(mcp, post):
    """Attach capabilities without copying business logic."""

    @mcp.tool()
    async def list_supported_services() -> dict:
        """Describe the major application service areas."""
        return {"services": ["meta_ads", "facebook_pages", "comments", "ga4", "clarity", "reports", "dashboards"]}
