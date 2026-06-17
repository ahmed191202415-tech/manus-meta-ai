from fastapi.testclient import TestClient
from fastapi import HTTPException

from app.analytics.dashboard_engine import build_fallback_funnel, build_live_funnel, stage_detail
from app.api import journey_dashboard_v7
from app.main import app


client = TestClient(app)


def test_journey_dashboard_page_renders_runtime():
    response = client.get("/journey-dashboard/v7")

    assert response.status_code == 200
    assert "Customer Journey Intelligence" in response.text
    assert "Conversion Path" in response.text
    assert "Comparison Lab" in response.text


def test_custom_dashboard_definition_returns_renderable_link():
    manifest = {
        "dashboard_id": "sales_probe_dashboard",
        "title": "Sales Probe",
        "filters": [
            {"key": "date_from", "type": "date", "default": "2026-06-15"},
            {"key": "date_to", "type": "date", "default": "2026-06-16"},
            {"key": "campaign_id", "type": "select", "options": [{"id": "all", "name": "All"}]},
        ],
        "metrics": {
            "purchase": {"source": "meta_action", "action_type": "purchase"},
        },
        "stages": [
            {"id": "purchase", "label": "Purchase", "metric_id": "purchase", "position": 1},
        ],
        "widgets": [
            {"id": "purchase_kpi", "type": "kpi", "title": "Purchases", "stage": "purchase", "span": 3},
            {"id": "stage_table", "type": "table", "title": "Stage Data", "source": "stages", "span": 12},
        ],
    }

    created = client.post("/api/dashboard-definitions", json=manifest)
    assert created.status_code == 200
    assert created.json()["url"].endswith("/dashboards/custom/sales_probe_dashboard")

    page = client.get("/dashboards/custom/sales_probe_dashboard")
    assert page.status_code == 200
    assert "Sales Probe" in page.text
    assert "purchase_kpi" in page.text
    assert "/api/dashboard-runtime/query" in page.text


def test_dashboard_definition_schema_exposes_manifest_fields():
    schema = app.openapi()
    body_ref = (
        schema["paths"]["/api/dashboard-definitions"]["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    )
    body_name = body_ref.split("/")[-1]
    properties = schema["components"]["schemas"][body_name]["properties"]

    for key in [
        "dashboard_id",
        "title",
        "description",
        "filters",
        "data_sources",
        "metrics",
        "stages",
        "charts",
        "widgets",
        "layout",
        "interactions",
        "runtime_queries",
        "formulas",
    ]:
        assert key in properties

    v2_post = schema["paths"]["/api/dashboard-definitions/v2"]["post"]
    assert v2_post["operationId"] == "create_dashboard_manifest_v2"
    v2_ref = v2_post["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    v2_name = v2_ref.split("/")[-1]
    v2_properties = schema["components"]["schemas"][v2_name]["properties"]
    assert "filters" in v2_properties
    assert "metrics" in v2_properties
    assert "runtime_queries" in v2_properties


def test_code_dashboard_definition_returns_renderable_link():
    code_dashboard = {
        "dashboard_id": "freeform_dashboard",
        "title": "Freeform Dashboard",
        "description": "A dashboard controlled by custom code.",
        "html": "<main id=\"app\"><h1>Freeform</h1><button id=\"load\">Load</button></main>",
        "css": "#app{padding:24px}.metric{font-weight:700}",
        "javascript": "document.getElementById('load').addEventListener('click',()=>window.ALLINGPT.runQuery('journey_funnel',{}));",
        "data_contract": {"queries": {"journey_funnel": {"source": "runtime"}}},
    }

    created = client.post("/api/dashboard-code/v1", json=code_dashboard)
    assert created.status_code == 200
    assert created.json()["url"].endswith("/dashboards/code/freeform_dashboard")

    page = client.get("/dashboards/code/freeform_dashboard")
    assert page.status_code == 200
    assert "Freeform Dashboard" in page.text
    assert "window.ALLINGPT" in page.text
    assert "runQuery" in page.text


def test_code_dashboard_schema_exposes_full_code_fields():
    schema = app.openapi()
    path = schema["paths"]["/api/dashboard-code/v1"]["post"]
    assert path["operationId"] == "create_full_code_dashboard_v1"
    body_ref = path["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    body_name = body_ref.split("/")[-1]
    properties = schema["components"]["schemas"][body_name]["properties"]

    for key in ["dashboard_id", "title", "description", "html", "css", "javascript", "data_contract"]:
        assert key in properties


def test_journey_funnel_returns_business_rule_stages():
    response = client.get("/api/journey/funnel?campaign_id=all")

    assert response.status_code == 200
    data = response.json()
    assert data["stages"][0]["id"] == "unique_ctr"
    assert any(stage["id"] == "register_page" and stage["source"] == "meta_event" for stage in data["stages"])
    assert data["debug"]["query_plan"]["calls"]


def test_stage_detail_register_page_uses_meta_event_not_lead():
    detail = stage_detail("register_page")

    assert detail["source"] == "meta_event"
    assert detail["metrics"][0]["label"] == "Register Page Event"
    assert detail["metrics"][0]["source"] == "meta"


def test_dashboard_runtime_query_supports_journey_funnel():
    response = client.post(
        "/api/dashboard-runtime/query",
        json={"dashboard_id": "customer_journey", "query_id": "journey_funnel", "filters": {"campaign_id": "all"}},
    )

    assert response.status_code == 200
    assert response.json()["stages"]


def test_dashboard_runtime_query_uses_live_meta_when_available(monkeypatch):
    async def fake_resolve_access_token(request):
        return "live-token"

    def fake_meta_call(method, path, token, params=None):
        assert method == "GET"
        assert path == "120244467443630505/insights"
        assert token == "live-token"
        assert params["time_range"] == {"since": "2026-06-15", "until": "2026-06-16"}
        return {
            "data": [
                {
                    "spend": "1594.31",
                    "impressions": "43706",
                    "reach": "11425",
                    "clicks": "441",
                    "inline_link_clicks": "157",
                    "unique_inline_link_clicks": "93",
                    "unique_ctr": "2.792123",
                    "actions": [
                        {"action_type": "onsite_conversion.messaging_conversation_started_7d", "value": "76"},
                        {"action_type": "lead", "value": "11"},
                    ],
                }
            ]
        }

    monkeypatch.setattr(journey_dashboard_v7, "resolve_access_token", fake_resolve_access_token)
    monkeypatch.setattr(journey_dashboard_v7, "meta_call", fake_meta_call)

    response = client.post(
        "/api/dashboard-runtime/query",
        json={
            "dashboard_id": "customer_journey",
            "query_id": "journey_funnel",
            "filters": {
                "campaign_id": "120244467443630505",
                "date_from": "2026-06-15",
                "date_to": "2026-06-16",
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["debug"]["mode"] == "live_data"
    assert data["spend"] == 1594.31
    assert data["summary"]["raw_meta"]["unique_inline_link_clicks"] == 93


def test_dashboard_runtime_query_uses_ga4_and_clarity_without_meta(monkeypatch):
    async def fake_resolve_access_token(request):
        raise HTTPException(status_code=401, detail="Meta is not connected.")

    def fake_run_ga4_report(tenant_id, property_id, dimensions, metrics, start_date, end_date, limit=100, **kwargs):
        assert tenant_id == "tenant@example.com"
        assert property_id == "529884683"
        if dimensions == ["eventName"]:
            return {
                "property_id": property_id,
                "dimensionHeaders": [{"name": "eventName"}],
                "metricHeaders": [{"name": "eventCount"}],
                "rows": [
                    {"dimensionValues": [{"value": "landing_stayed_10s"}], "metricValues": [{"value": "42"}]},
                ],
            }
        return {
            "property_id": property_id,
            "dimensionHeaders": [],
            "metricHeaders": [{"name": metric} for metric in metrics],
            "rows": [{"metricValues": [{"value": "100"} for _ in metrics]}],
        }

    def fake_clarity(tenant_id, num_of_days, dimensions):
        assert tenant_id == "tenant@example.com"
        return {
            "tenant_id": tenant_id,
            "dimensions": dimensions,
            "raw": [
                {
                    "metricName": "QuickbackClick",
                    "information": [{"URL": "https://beon.chat/", "subTotal": 7, "totalSessionCount": 100}],
                }
            ],
        }

    monkeypatch.setattr(journey_dashboard_v7, "resolve_access_token", fake_resolve_access_token)
    monkeypatch.setattr(journey_dashboard_v7, "run_ga4_report", fake_run_ga4_report)
    monkeypatch.setattr(journey_dashboard_v7, "run_clarity_live_insights_with_fallbacks", fake_clarity)

    manifest = {
        "dashboard_id": "ga4_clarity_probe",
        "title": "GA4 Clarity Probe",
        "data_sources": {
            "ga4": {"property_id": "529884683"},
            "clarity": {"connector": "clarity"},
        },
        "metrics": {
            "stayed_10s": {"source": "ga4", "event_name": "landing_stayed_10s"},
            "quickback": {"source": "clarity", "field": "quickback"},
        },
        "stages": [
            {"id": "stayed_10s", "label": "Stayed 10s", "metric_id": "stayed_10s", "position": 1},
            {"id": "quickback", "label": "Quickback", "metric_id": "quickback", "position": 2},
        ],
    }
    client.post("/api/dashboard-definitions/v2", json=manifest)

    response = client.post(
        "/api/dashboard-runtime/query",
        json={
            "dashboard_id": "ga4_clarity_probe",
            "query_id": "journey_funnel",
            "filters": {
                "tenant_id": "tenant@example.com",
                "property_id": "529884683",
                "date_from": "2026-06-15",
                "date_to": "2026-06-16",
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    by_id = {stage["id"]: stage for stage in data["stages"]}
    assert data["debug"]["mode"] == "mixed_live_data"
    assert data["debug"]["connector_status"]["meta"] == "auth_failed"
    assert data["debug"]["connector_status"]["ga4"] == "success"
    assert data["debug"]["connector_status"]["clarity"] == "success"
    assert by_id["stayed_10s"]["numeric_value"] == 42
    assert by_id["quickback"]["numeric_value"] == 7


def test_code_dashboard_runtime_uses_own_data_contract_not_customer_journey(monkeypatch):
    async def fake_resolve_access_token(request):
        raise HTTPException(status_code=401, detail="Meta is not connected.")

    def fake_run_ga4_report(tenant_id, property_id, dimensions, metrics, start_date, end_date, limit=100, **kwargs):
        if dimensions == ["eventName"]:
            return {
                "property_id": property_id,
                "dimensionHeaders": [{"name": "eventName"}],
                "metricHeaders": [{"name": "eventCount"}],
                "rows": [
                    {"dimensionValues": [{"value": "otp_screen_view"}], "metricValues": [{"value": "12"}]},
                ],
            }
        return {"property_id": property_id, "dimensionHeaders": [], "metricHeaders": [], "rows": []}

    monkeypatch.setattr(journey_dashboard_v7, "resolve_access_token", fake_resolve_access_token)
    monkeypatch.setattr(journey_dashboard_v7, "run_ga4_report", fake_run_ga4_report)

    client.post(
        "/api/dashboard-code/v1",
        json={
            "dashboard_id": "otp_code_dashboard",
            "title": "OTP Code Dashboard",
            "html": "<div id='app'></div>",
            "javascript": "window.ALLINGPT.runQuery('blended_journey',{tenant_id:'tenant@example.com'})",
            "data_contract": {
                "data_sources": {"ga4": {"property_id": "529884683"}},
                "metrics": {
                    "otp_views": {"source": "ga4_event", "event_name": "otp_screen_view"},
                    "otp_rate": {"source": "formula", "expression": "otp_views / 24"},
                },
                "stages": [
                    {"id": "otp_views", "label": "OTP Views", "metric_id": "otp_views", "position": 1},
                    {"id": "otp_rate", "label": "OTP Rate", "metric_id": "otp_rate", "position": 2},
                ],
            },
        },
    )

    response = client.post(
        "/api/dashboard-runtime/query",
        json={
            "dashboard_id": "otp_code_dashboard",
            "query_id": "blended_journey",
            "filters": {"tenant_id": "tenant@example.com", "property_id": "529884683"},
        },
    )

    assert response.status_code == 200
    data = response.json()
    by_id = {stage["id"]: stage for stage in data["stages"]}
    assert data["dashboard_id"] == "otp_code_dashboard"
    assert data["debug"]["query_plan"]["dashboard_id"] == "otp_code_dashboard"
    assert "customer_journey" not in data["debug"]["query_plan"]["dashboard_id"]
    assert by_id["otp_views"]["numeric_value"] == 12
    assert by_id["otp_rate"]["numeric_value"] == 0.5
    assert data["source_map"]["otp_views"]["source"] == "ga4_event"
    assert data["filters_sent"]["tenant_id"] == "tenant@example.com"


def test_dashboard_runtime_supports_ga4_page_metric(monkeypatch):
    async def fake_resolve_access_token(request):
        raise HTTPException(status_code=401, detail="Meta is not connected.")

    def fake_run_ga4_report(tenant_id, property_id, dimensions, metrics, start_date, end_date, limit=100, **kwargs):
        assert kwargs["filters"]["page_path_contains"] == "verify-otp"
        return {
            "property_id": property_id,
            "dimensionHeaders": [{"name": "pagePathPlusQueryString"}],
            "metricHeaders": [{"name": "sessions"}],
            "rows": [
                {"dimensionValues": [{"value": "/verify-otp"}], "metricValues": [{"value": "31"}]},
            ],
        }

    monkeypatch.setattr(journey_dashboard_v7, "resolve_access_token", fake_resolve_access_token)
    monkeypatch.setattr(journey_dashboard_v7, "run_ga4_report", fake_run_ga4_report)

    client.post(
        "/api/dashboard-definitions/v2",
        json={
            "dashboard_id": "website_analytics_probe",
            "data_sources": {"ga4": {"property_id": "529884683"}},
            "metrics": {"otp_page_sessions": {"source": "ga4_page", "page_path_contains": "verify-otp", "metric": "sessions"}},
            "stages": [{"id": "otp_page_sessions", "label": "OTP Page Sessions", "metric_id": "otp_page_sessions", "position": 1}],
        },
    )

    response = client.post(
        "/api/dashboard-runtime/query",
        json={"dashboard_id": "website_analytics_probe", "query_id": "ga4_report", "filters": {"tenant_id": "tenant@example.com"}},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["dashboard_id"] == "website_analytics_probe"
    assert data["stages"][0]["numeric_value"] == 31
    assert data["connector_status"]["ga4"] == "success"


def test_journey_funnel_uses_live_meta_without_server_error(monkeypatch):
    async def fake_resolve_access_token(request):
        return "live-token"

    def fake_meta_call(method, path, token, params=None):
        assert path == "120244467443630505/insights"
        return {
            "data": [
                {
                    "spend": "1594.31",
                    "unique_inline_link_clicks": "93",
                    "unique_ctr": "2.792123",
                    "actions": [{"action_type": "landing_page_view", "value": "27"}],
                }
            ]
        }

    monkeypatch.setattr(journey_dashboard_v7, "resolve_access_token", fake_resolve_access_token)
    monkeypatch.setattr(journey_dashboard_v7, "meta_call", fake_meta_call)

    response = client.get(
        "/api/journey/funnel?campaign_id=120244467443630505&date_from=2026-06-15&date_to=2026-06-16"
    )

    assert response.status_code == 200
    assert response.json()["debug"]["mode"] == "live_data"
    assert response.json()["spend"] == 1594.31


def test_runtime_filters_prioritize_ad_then_adset_then_campaign(monkeypatch):
    async def fake_resolve_access_token(request):
        return "live-token"

    def fake_meta_call(method, path, token, params=None):
        assert path == "ad_123/insights"
        assert params["time_range"] == {"since": "2026-06-15", "until": "2026-06-16"}
        assert "date_preset" not in params
        return {"data": [{"spend": "10", "unique_ctr": "1", "unique_inline_link_clicks": "2"}]}

    monkeypatch.setattr(journey_dashboard_v7, "resolve_access_token", fake_resolve_access_token)
    monkeypatch.setattr(journey_dashboard_v7, "meta_call", fake_meta_call)

    response = client.post(
        "/api/dashboard-runtime/query",
        json={
            "dashboard_id": "customer_journey",
            "query_id": "journey_funnel",
            "filters": {
                "campaign_id": "campaign_123",
                "adset_id": "adset_123",
                "ad_id": "ad_123",
                "date_from": "2026-06-15",
                "date_to": "2026-06-16",
            },
        },
    )

    data = response.json()
    assert response.status_code == 200
    assert data["debug"]["meta_path"] == "ad_123/insights"
    assert data["debug"]["entity_scope"] == {"type": "ad", "id": "ad_123"}
    assert data["debug"]["filters_sent"]["campaign_id"] == "campaign_123"


def test_connector_registry_exposes_metric_dictionary():
    response = client.get("/api/dashboard-runtime/connectors")

    assert response.status_code == 200
    data = response.json()
    assert "meta" in data["connectors"]
    assert data["metrics"]["register_page"]["source"] == "meta_event"


def test_live_funnel_does_not_map_fb_pixel_custom_to_register_page():
    funnel = build_live_funnel(
        {
            "data": [
                {
                    "spend": "500",
                    "unique_ctr": "4.887675",
                    "unique_inline_link_clicks": "47",
                    "actions": [
                        {"action_type": "landing_page_view", "value": "27"},
                        {"action_type": "lead", "value": "25"},
                        {"action_type": "complete_registration", "value": "2"},
                        {"action_type": "purchase", "value": "2"},
                        {"action_type": "offsite_conversion.fb_pixel_custom", "value": "72"},
                    ],
                }
            ]
        }
    )

    by_id = {stage["id"]: stage for stage in funnel["stages"]}
    assert by_id["unique_ctr"]["numeric_value"] == 4.887675
    assert by_id["unique_link_clicks"]["numeric_value"] == 47
    assert by_id["landing_loaded"]["numeric_value"] == 27
    assert by_id["register_page"]["numeric_value"] == 0
    assert by_id["complete_registration"]["numeric_value"] == 2
    assert by_id["purchase"]["numeric_value"] == 2
    assert by_id["register_page"]["warnings"] == ["Event not found: Register Page"]
    assert funnel["debug"]["unmapped_events"] == [
        {
            "action_type": "offsite_conversion.fb_pixel_custom",
            "value": 72.0,
            "reason": "Not mapped by dashboard definition",
            "status": "unmapped",
        }
    ]


def test_event_discovery_marks_fb_pixel_custom_unmapped(monkeypatch):
    async def fake_resolve_access_token(request):
        return "live-token"

    def fake_meta_call(method, path, token, params=None):
        if path.endswith("/insights"):
            return {
                "data": [
                    {
                        "actions": [
                            {"action_type": "landing_page_view", "value": "27"},
                            {"action_type": "offsite_conversion.fb_pixel_custom", "value": "72"},
                        ]
                    }
                ]
            }
        if path.endswith("/customconversions"):
            return {"data": [{"id": "cc_1", "name": "Register Page"}]}
        return {"data": []}

    monkeypatch.setattr(journey_dashboard_v7, "resolve_access_token", fake_resolve_access_token)
    monkeypatch.setattr(journey_dashboard_v7, "meta_call", fake_meta_call)

    response = client.get(
        "/api/dashboard-runtime/events/discover?account_id=act_1&campaign_id=120247668860760505&date_from=2026-06-15&date_to=2026-06-16"
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "needs_mapping"
    assert any(item["action_type"] == "offsite_conversion.fb_pixel_custom" and item["status"] == "unmapped" for item in data["meta_actions"])


def test_fallback_funnel_calculates_transition_and_costs():
    funnel = build_fallback_funnel()
    register = next(stage for stage in funnel["stages"] if stage["id"] == "register_page")

    assert register["transition_rate"] is not None
    assert register["drop_rate"] is not None
    assert register["cost"] > 0
