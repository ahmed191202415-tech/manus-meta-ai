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


def test_ga4_dispatcher_accepts_flat_property_selection_from_chatgpt(monkeypatch):
    async def fake_handler(body, request):
        return {"property_id": body.property_id, "property_name": body.property_name}

    monkeypatch.setattr(gpt_tools.ga4, "ga4_select_property", fake_handler)
    result = asyncio.run(
        gpt_tools.ga4_tool(
            GA4ToolRequest(action="select_property", property_id="529884683", property_name="BeOn"),
            object(),
        )
    )

    assert result == {"property_id": "529884683", "property_name": "BeOn"}


def test_ga4_dispatcher_accepts_flat_custom_event_report_from_chatgpt(monkeypatch):
    async def fake_handler(body, request):
        return {
            "property_id": body.property_id,
            "dimensions": body.dimensions,
            "metrics": body.metrics,
            "dimension_filters": [item.model_dump() for item in body.dimension_filters],
        }

    monkeypatch.setattr(gpt_tools.ga4, "ga4_custom_report", fake_handler)
    result = asyncio.run(
        gpt_tools.ga4_tool(
            GA4ToolRequest(
                action="custom_report",
                property_id="529884683",
                start_date="2026-05-03",
                end_date="2026-06-02",
                dimensions=["date", "eventName"],
                metrics=["eventCount"],
                dimension_filters=[
                    {"dimension": "eventName", "operator": "exact", "value": "OnboardingRegistration"},
                ],
                limit=100,
            ),
            object(),
        )
    )

    assert result == {
        "property_id": "529884683",
        "dimensions": ["date", "eventName"],
        "metrics": ["eventCount"],
        "dimension_filters": [
            {
                "dimension": "eventName",
                "operator": "exact",
                "value": "OnboardingRegistration",
                "values": [],
                "case_sensitive": False,
                "exclude": False,
            }
        ],
    }


def test_ga4_schema_exposes_flat_custom_report_fields():
    schema = openapi_gpt_schema()
    properties = schema["components"]["schemas"]["GA4ToolRequest"]["properties"]

    for key in ("property_id", "start_date", "end_date", "dimensions", "metrics", "dimension_filters", "sort", "limit"):
        assert key in properties


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


def test_meta_tracking_schema_exposes_lead_ads_actions_and_fields():
    schema = openapi_gpt_schema()
    properties = schema["components"]["schemas"]["MetaTrackingToolRequest"]["properties"]

    for action in ("diagnose_lead_access", "lead_forms", "form_leads"):
        assert action in properties["action"]["enum"]
    for key in ("page_id", "form_id"):
        assert key in properties


def test_meta_tracking_diagnoses_missing_pages_manage_ads(monkeypatch):
    def fake_meta_call(method, path, token, params=None):
        if path == "me/permissions":
            return {
                "data": [
                    {"permission": "leads_retrieval", "status": "granted"},
                    {"permission": "pages_show_list", "status": "granted"},
                    {"permission": "pages_read_engagement", "status": "granted"},
                ]
            }
        raise AssertionError(path)

    monkeypatch.setattr(gpt_tools, "meta_call", fake_meta_call)
    monkeypatch.setattr(gpt_tools, "resolve_page_token_for_page_id", lambda token, page_id: "page_token")
    result = asyncio.run(
        gpt_tools.meta_tracking_tool(
            MetaTrackingToolRequest(action="diagnose_lead_access", page_id="487462921107773"),
            token="user_token",
        )
    )

    assert result["missing_required_permissions"] == ["pages_manage_ads"]
    assert result["can_read_lead_forms"] is False
    assert "Add pages_manage_ads" in result["next_steps"][0]


def test_meta_tracking_form_leads_use_page_token(monkeypatch):
    calls = []
    monkeypatch.setattr(gpt_tools, "resolve_page_token_for_page_id", lambda token, page_id: "page_token")
    monkeypatch.setattr(
        gpt_tools,
        "meta_call",
        lambda method, path, token, params=None: calls.append((method, path, token, params)) or {"data": []},
    )

    result = asyncio.run(
        gpt_tools.meta_tracking_tool(
            MetaTrackingToolRequest(
                action="form_leads",
                page_id="487462921107773",
                form_id="2028631861367601",
                limit=25,
            ),
            token="user_token",
        )
    )

    assert result == {"data": []}
    assert calls[0][0:3] == ("GET", "2028631861367601/leads", "page_token")
    assert calls[0][3]["limit"] == 25


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


def test_website_dispatcher_accepts_flat_property_id(monkeypatch):
    async def fake_handler(body, request):
        return {"property_id": body.property_id}

    monkeypatch.setattr(gpt_tools.website_analysis, "website_analyze", fake_handler)
    result = asyncio.run(
        gpt_tools.website_tool(
            WebsiteToolRequest(action="analyze", property_id="529884683"),
            object(),
        )
    )

    assert result == {"property_id": "529884683"}


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


def test_journey_dispatcher_accepts_flat_account_id(monkeypatch):
    async def fake_handler(body, request):
        return {"account_id": body.meta_account_id, "property_id": body.ga4_property_id}

    monkeypatch.setattr(gpt_tools.journey, "journey_analyze", fake_handler)
    result = asyncio.run(
        gpt_tools.journey_tool(
            JourneyToolRequest(action="analyze", meta_account_id="act_1", ga4_property_id="529884683"),
            object(),
        )
    )

    assert result == {"account_id": "act_1", "property_id": "529884683"}


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


def test_clarity_dispatcher_accepts_flat_days(monkeypatch):
    async def fake_handler(body, request):
        return {"days": body.num_of_days}

    monkeypatch.setattr(gpt_tools.clarity, "clarity_summary", fake_handler)
    result = asyncio.run(
        gpt_tools.clarity_tool(
            ClarityToolRequest(action="summary", num_of_days=3),
            object(),
        )
    )

    assert result == {"days": 3}


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


def test_report_dispatcher_accepts_flat_pptx_fields(monkeypatch):
    async def fake_handler(body):
        return {"title": body.title, "slide_count": len(body.slides)}

    monkeypatch.setattr(gpt_tools.reports, "save_pptx_report", fake_handler)
    result = asyncio.run(
        gpt_tools.report_tool(
            ReportToolRequest(action="pptx", title="Weekly report", slides=[]),
        )
    )

    assert result == {"title": "Weekly report", "slide_count": 0}
