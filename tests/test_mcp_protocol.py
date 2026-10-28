"""Exercise mounted MCP Streamable HTTP with a single lifespan."""
from fastapi.testclient import TestClient

from app.main import app


HEADERS = {
    "accept": "application/json, text/event-stream",
    "content-type": "application/json",
    "mcp-protocol-version": "2025-06-18",
}


def _jsonrpc(method, request_id, params=None):
    value = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        value["params"] = params
    return value


def test_mcp_initialize_tools_and_access_control():
    # A StreamableHTTPSessionManager is single-use per app lifespan.
    # The local host header must match the MCP transport allowlist.
    with TestClient(app, base_url="http://localhost:8000") as client:
        response = client.post("/mcp/", headers=HEADERS, json=_jsonrpc(
            "initialize", 1, {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "1.0"},
            },
        ))
        assert response.status_code == 200, response.text
        assert "result" in response.json()

        listed = client.post("/mcp/", headers=HEADERS, json=_jsonrpc("tools/list", 2))
        assert listed.status_code == 200, listed.text
        names = {tool["name"] for tool in listed.json()["result"]["tools"]}
        assert {"create_meta_asset", "page_comment_automation", "dashboard_runtime"} <= names

        denied = client.post("/mcp/", headers=HEADERS, json=_jsonrpc(
            "tools/call", 3, {"name": "discover_accounts", "arguments": {}},
        ))
        assert denied.status_code == 200, denied.text
        assert denied.json()["result"]["isError"] is True
