import asyncio

from app.api import gpt_tools
from app.main import app, openapi_gpt_schema
from app.schemas.gpt_tool_requests import (
    ClarityToolRequest,
    GA4ToolRequest,
    JourneyToolRequest,
    MetaTrackingToolRequest,
    ReportToolRequest,
    WebsiteToolRequest,
)


def test_compact_gpt_schema_keeps_broad_dispatchers_only():
    schema = openapi_gpt_schema()

    assert set(schema["paths"]) == {
        "/analysis/run",
        "/meta/query",
        "/meta/request",
        "/comment_automations/manage",
        "/tools/ga4",
        "/tools/meta_tracking",
        "/tools/website",
        "/tools/journey",
        "/tools/clarity",
        "/tools/reports",
    }
    assert "/ga4/custom_report" in app.openapi()["paths"]
    assert "/reports/save_pptx" in app.openapi()["paths"]
    assert "/page_posts" in app.openapi()["paths"]


def test_gpt_operation_descriptions_fit_chatgpt_import_limit():
    schema = openapi_gpt_schema()

    for path, path_item in schema["paths"].items():
        for method, operation in path_item.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            assert len(operation.get("description", "")) <= 300, f"{method.upper()} {path} description is too long"


def test_ga4_dispatcher_routes_custom_report(monkeypatch):
    calls = []

    async def fake_handler(body, request):
        calls.append((body, request))
        return {"ok": True}

    monkeypatch.setattr(gpt_tools.ga4, "ga4_custom_report", fake_handler)
    request = object()
    result = asyncio.run(
        gpt_tools.ga4_tool(
            GA4ToolRequest(
                action="custom_report",
                payload={"dimensions": ["eventName"], "metrics": ["eventCount"]},
            ),
            request,
        )
    )

    assert result == {"ok": True}
    assert calls[0][0].dimensions == ["eventName"]
    assert calls[0][1] is request


def test_meta_tracking_dispatcher_routes_received_pixel_events(monkeypatch):
    calls = []

    async def fake_handler(body, token):
        calls.append((body, token))
        return {"event_names": ["PageView", "Lead"]}

    monkeypatch.setattr(gpt_tools.pixels, "pixel_event_catalog", fake_handler)
    result = asyncio.run(
        gpt_tools.meta_tracking_tool(
            MetaTrackingToolRequest(action="received_pixel_events", payload={"pixel_id": "123"}),
            token="user_token",
        )
    )

    assert result == {"event_names": ["PageView", "Lead"]}
    assert calls[0][0].pixel_id == "123"
    assert calls[0][1] == "user_token"


def test_meta_tracking_dispatcher_accepts_flat_pixel_id_from_chatgpt(monkeypatch):
    async def fake_handler(body, token):
        return {"pixel_id": body.pixel_id, "token": token}

    monkeypatch.setattr(gpt_tools.pixels, "pixel_event_catalog", fake_handler)
    result = asyncio.run(
        gpt_tools.meta_tracking_tool(
            MetaTrackingToolRequest(action="received_pixel_events", pixel_id="2025821897925927"),
            token="user_token",
        )
    )

    assert result == {"pixel_id": "2025821897925927", "token": "user_token"}


def test_meta_tracking_schema_exposes_flat_pixel_id():
    schema = openapi_gpt_schema()
    properties = schema["components"]["schemas"]["MetaTrackingToolRequest"]["properties"]

    assert "pixel_id" in properties
    assert "account_id" in properties
    assert properties["pixel_id"]["description"] == "Meta Pixel ID for received_pixel_events."


def test_website_dispatcher_routes_focused_analysis(monkeypatch):
    async def fake_handler(body, request):
        return {"action": "device_analysis", "property_id": body.property_id}

    monkeypatch.setattr(gpt_tools.website_analysis, "website_device_analysis", fake_handler)
    result = asyncio.run(
        gpt_tools.website_tool(
            WebsiteToolRequest(action="device_analysis", payload={"property_id": "123"}),
            object(),
        )
    )

    assert result == {"action": "device_analysis", "property_id": "123"}


def test_journey_dispatcher_routes_decision(monkeypatch):
    async def fake_handler(body, request):
        return {"action": "decision", "account_id": body.meta_account_id}

    monkeypatch.setattr(gpt_tools.journey, "journey_decision", fake_handler)
    result = asyncio.run(
        gpt_tools.journey_tool(
            JourneyToolRequest(action="decision", payload={"meta_account_id": "act_1"}),
            object(),
        )
    )

    assert result == {"action": "decision", "account_id": "act_1"}


def test_clarity_dispatcher_routes_pages(monkeypatch):
    async def fake_handler(body, request):
        return {"action": "pages", "days": body.num_of_days}

    monkeypatch.setattr(gpt_tools.clarity, "clarity_pages", fake_handler)
    result = asyncio.run(
        gpt_tools.clarity_tool(
            ClarityToolRequest(action="pages", payload={"num_of_days": 2}),
            object(),
        )
    )

    assert result == {"action": "pages", "days": 2}


def test_report_dispatcher_restores_pptx_generation(monkeypatch):
    async def fake_handler(body):
        return {"action": "pptx", "title": body.title}

    monkeypatch.setattr(gpt_tools.reports, "save_pptx_report", fake_handler)
    result = asyncio.run(
        gpt_tools.report_tool(
            ReportToolRequest(action="pptx", payload={"title": "Weekly report", "slides": []}),
        )
    )

    assert result == {"action": "pptx", "title": "Weekly report"}
