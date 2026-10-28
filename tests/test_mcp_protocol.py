"""Exercise the actual mounted MCP JSON-RPC transport without Meta credentials."""
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


def test_mcp_initialize_and_list_tools():
    with TestClient(app) as client:
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
        assert "create_meta_asset" in names
        assert "page_comment_automation" in names
        assert "dashboard_runtime" in names


def test_mcp_rejects_missing_credentials_for_data_access():
    with TestClient(app) as client:
        response = client.post("/mcp/", headers=HEADERS, json=_jsonrpc(
            "tools/call", 3, {"name": "discover_accounts", "arguments": {}},
        ))
        assert response.status_code == 200, response.text
        assert response.json()["result"]["isError"] is True
