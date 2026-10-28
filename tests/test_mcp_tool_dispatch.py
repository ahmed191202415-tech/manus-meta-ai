"""Validate MCP facade routing without calling Facebook, Google or storage."""
import asyncio

from app.mcp_actions import register_action_tools
from app.mcp_reporting import register_reporting_tools
from app.mcp_capabilities import register_tools


class Collector:
    def __init__(self):
        self.tools = {}

    def tool(self):
        def wrap(fn):
            self.tools[fn.__name__] = fn
            return fn
        return wrap


def setup_tools():
    registry = Collector()
    calls = []

    async def post(path, values):
        calls.append((path, values))
        return {"ok": True, "path": path, "payload": values}

    register_action_tools(registry, post)
    register_reporting_tools(registry, post)
    register_tools(registry, post)
    return registry.tools, calls


def test_create_campaign_uses_existing_create_endpoint(monkeypatch):
    monkeypatch.setenv("MCP_WRITES_ENABLED", "true")
    tools, calls = setup_tools()
    result = asyncio.run(tools["create_meta_asset"]("campaign", {
        "account_id": "123", "name": "Draft", "objective": "OUTCOME_TRAFFIC",
    }, confirmed=True))
    assert result["path"] == "/campaigns"
    assert calls[0][1]["status"] == "PAUSED"


def test_page_reply_moderation_and_rule_actions(monkeypatch):
    monkeypatch.setenv("MCP_WRITES_ENABLED", "true")
    tools, calls = setup_tools()
    asyncio.run(tools["reply_to_page_comment"](
        page_id="123", comment_id="456", message="Thanks", confirmed=True))
    assert calls[-1][0] == "/page_comments/456/reply?page_id=123"

    asyncio.run(tools["moderate_page_comment"](
        page_id="123", comment_id="456", confirmed=True))
    assert calls[-1][0] == "/page_comments/456/hide?page_id=123"

    asyncio.run(tools["page_comment_automation"](
        action="list_rules", values={"tenant_id": "demo"}))
    assert calls[-1][0] == "/comment_automations/manage"
    assert calls[-1][1]["action"] == "list_rules"

    asyncio.run(tools["page_comment_automation"](
        action="create_rule", values={"page_id": "123",
            "public_reply_message": "Hello"}, confirmed=True))
    assert calls[-1][1]["action"] == "create_rule"


def test_reports_dashboard_and_runtime_map_to_existing_operations(monkeypatch):
    monkeypatch.setenv("MCP_WRITES_ENABLED", "true")
    tools, calls = setup_tools()

    asyncio.run(tools["generate_report"]("pdf", {"title": "Summary", "sections": []}, confirmed=True))
    assert calls[-1][0] == "/tools/reports"

    asyncio.run(tools["manage_dashboards"]("list_dashboards", {}))
    assert calls[-1][0] == "/tools/dashboards"

    asyncio.run(tools["dashboard_runtime"]("capabilities", {}))
    assert calls[-1][0] == "/api/dashboard-runtime/v2/workflow"

    asyncio.run(tools["google_analytics"]("select_property", {"property_id": "456"}, confirmed=True))
    assert calls[-1][0] == "/tools/ga4"
