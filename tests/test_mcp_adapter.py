from app.mcp_server import mcp, mcp_asgi_app


def test_mcp_adapter_exposes_http_app():
    assert mcp_asgi_app is not None
    assert mcp.name == "Super Ad Analysis"
