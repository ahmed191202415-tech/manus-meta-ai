import asyncio

import pytest

from app.main import app
from app.mcp_server import mcp, mcp_asgi_app
from app.mcp_actions import require_write


def test_mcp_is_mounted_and_tools_are_discoverable():
    assert mcp_asgi_app is not None
    assert any(getattr(route, "path", "") == "/mcp" for route in app.routes)
    names = {tool.name for tool in asyncio.run(mcp.list_tools())}
    expected = {
        "discover_accounts", "meta_insights", "run_analysis",
        "route_analysis_request", "meta_graph_read", "meta_tracking",
        "google_analytics", "website_intelligence", "customer_journey",
        "clarity_analysis", "list_campaigns", "list_ad_sets", "list_ads",
        "list_facebook_pages", "list_page_posts", "list_page_comments",
        "create_meta_asset", "update_meta_asset", "create_page_post",
        "reply_to_page_comment", "moderate_page_comment", "page_comment_automation",
        "generate_report", "manage_dashboards", "dashboard_runtime",
    }
    assert expected.issubset(names)


def test_mcp_writes_disabled_by_default(monkeypatch):
    monkeypatch.delenv("MCP_WRITES_ENABLED", raising=False)
    with pytest.raises(ValueError, match="disabled"):
        require_write(True)


def test_mcp_write_requires_confirmation(monkeypatch):
    monkeypatch.setenv("MCP_WRITES_ENABLED", "true")
    with pytest.raises(ValueError, match="approval"):
        require_write(False)
    require_write(True)
