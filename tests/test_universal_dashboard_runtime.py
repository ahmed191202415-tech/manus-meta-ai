from fastapi.testclient import TestClient

from app.api import dashboard_runtime
from app.core import dashboard_runtime as runtime
from app.main import app
from app.schemas.dashboard_runtime_requests import DashboardPlanValidateRequest
from app.core.dashboard_plan import resolve_templates
from app.core.dashboard_transforms import build_funnel, build_options, safe_formula


client = TestClient(app)


def _cascading_plan():
    return {
        "id": "global_filters",
        "title": "Global filters",
        "nodes": [
            {"id": "accounts", "connector": "meta", "operation": "list_accounts", "run_when": "on_open"},
            {
                "id": "campaigns",
                "connector": "meta",
                "operation": "list_campaigns",
                "params": {"account_id": "{{inputs.account_id}}"},
                "required_inputs": ["account_id"],
                "run_when": "on_change",
            },
            {
                "id": "campaign_options",
                "connector": "transform",
                "operation": "options",
                "params": {"from": "campaigns", "label_field": "name", "value_field": "id"},
                "depends_on": ["campaigns"],
                "run_when": "on_change",
            },
        ],
        "output": {"campaigns": "{{nodes.campaign_options}}"},
    }


def _funnel_plan():
    return {
        "id": "customer_journey_funnel",
        "nodes": [
            {
                "id": "assemble",
                "connector": "transform",
                "operation": "funnel",
                "params": {
                    "spend": {"from": "meta", "path": "data.0.spend"},
                    "stages": [
                        {
                            "id": "external_clicks",
                            "label": "External link clicks",
                            "source": "meta",
                            "value": {"from": "meta", "path": "data.0.unique_inline_link_clicks"},
                        },
                        {
                            "id": "register_page",
                            "label": "Register Page",
                            "source": "meta_event",
                            "value": {
                                "from": "meta",
                                "rows_path": "data.0.actions",
                                "where": {"action_type": "Register Page"},
                                "value_field": "value",
                            },
                        },
                    ],
                },
                "depends_on": ["meta"],
            },
            {
                "id": "meta",
                "connector": "meta",
                "operation": "insights",
                "params": {"scope_id": "act_1"},
            },
        ],
        "output": {
            "stages": "{{nodes.assemble.stages}}",
            "complete": "{{nodes.assemble.complete}}",
            "status": "{{nodes.assemble.status}}",
        },
    }


def test_runtime_capabilities_are_generic_not_dashboard_specific():
    response = client.get("/api/dashboard-runtime/v2/capabilities")
    assert response.status_code == 200
    connectors = {item["id"]: item for item in response.json()["connectors"]}
    assert {"meta", "ga4", "clarity", "transform"} <= set(connectors)
    assert "list_campaigns" in {item["id"] for item in connectors["meta"]["operations"]}
    assert response.json()["workflow"] == ["validate", "preview", "user_confirmation", "publish"]


def test_plan_validation_understands_dependencies_and_inputs():
    response = client.post("/api/dashboard-runtime/v2/validate", json={"plan": _cascading_plan()})
    assert response.status_code == 200
    assert response.json()["valid"] is True
    assert response.json()["execution_order"] == ["accounts", "campaigns", "campaign_options"]


def test_plan_rejects_unknown_connector_operation():
    plan = _cascading_plan()
    plan["nodes"][0]["operation"] = "guess_what_user_means"
    response = client.post("/api/dashboard-runtime/v2/validate", json={"plan": plan})
    assert response.status_code == 200
    assert response.json()["valid"] is False
    assert "Unsupported operation" in response.json()["errors"][0]["message"]


def test_plan_rejects_template_dependency_that_is_not_declared():
    plan = _cascading_plan()
    plan["nodes"][2]["depends_on"] = []
    plan["nodes"][2]["params"]["from"] = "{{nodes.campaigns}}"

    response = client.post("/api/dashboard-runtime/v2/validate", json={"plan": plan})

    assert response.status_code == 200
    assert response.json()["valid"] is False
    assert "depends_on" in response.json()["errors"][0]["message"]


def test_template_interpolation_preserves_zero_and_false_values():
    context = {"inputs": {"count": 0, "enabled": False}}

    assert resolve_templates("count={{inputs.count}}", context) == "count=0"
    assert resolve_templates("enabled={{inputs.enabled}}", context) == "enabled=False"


def test_options_skip_rows_without_values_and_fallback_to_value_label():
    results = {"campaigns": {"data": [{"id": "1", "name": "One"}, {"id": "2"}, {"name": "Missing"}]}}

    assert build_options({"from": "campaigns"}, results) == [
        {"label": "One", "value": "1"},
        {"label": "2", "value": "2"},
    ]


def test_formula_supports_negative_values_and_safe_zero_division():
    assert safe_formula("-spend + revenue", {"spend": 10.0, "revenue": 25.0}) == 15.0
    assert safe_formula("revenue / 0", {"revenue": 25.0}) is None


def test_generic_funnel_transform_builds_live_stage_contract():
    result = build_funnel(
        {
            "spend": {"from": "meta", "path": "data.0.spend"},
            "stages": [
                {
                    "id": "clicks",
                    "label": "External link clicks",
                    "source": "meta",
                    "value": {"from": "meta", "path": "data.0.unique_inline_link_clicks"},
                },
                {
                    "id": "register",
                    "label": "Register Page",
                    "source": "meta_event",
                    "value": {
                        "from": "meta",
                        "rows_path": "data.0.actions",
                        "where": {"action_type": "Register Page"},
                        "value_field": "value",
                    },
                    "revenue": 300,
                },
            ],
        },
        {
            "meta": {
                "data": [
                    {
                        "spend": "200",
                        "unique_inline_link_clicks": "40",
                        "actions": [{"action_type": "Register Page", "value": "10"}],
                    }
                ]
            }
        },
    )

    assert result["complete"] is True
    assert result["stages"][1]["numeric_value"] == 10
    assert result["stages"][1]["cost"] == 20
    assert result["stages"][1]["transition_rate"] == 0.25
    assert result["stages"][1]["drop_rate"] == 0.75
    assert result["stages"][1]["roas"] == 1.5


def test_funnel_transform_marks_unmapped_live_stage_incomplete():
    result = build_funnel(
        {
            "stages": [
                {"id": "clicks", "label": "Clicks", "source": "meta", "value": 12},
                {
                    "id": "register",
                    "label": "Register",
                    "source": "meta_event",
                    "value": {"from": "meta", "rows_path": "data.0.actions", "where": {"action_type": "missing"}},
                },
            ]
        },
        {"meta": {"data": [{"actions": []}]}},
    )

    assert result["complete"] is False
    assert result["stages"][1]["source_status"] == "missing"
    assert result["missing_sources"][0]["stage_id"] == "register"


def test_cascading_campaign_query_uses_selected_account_and_real_meta_path(monkeypatch):
    async def fake_token(request):
        return "token"

    calls = []

    def fake_meta_call(method, path, token, params=None):
        calls.append({"method": method, "path": path, "token": token, "params": params})
        return {"data": [{"id": "cmp_1", "name": "Campaign One"}]}

    monkeypatch.setattr(runtime, "resolve_access_token", fake_token)
    monkeypatch.setattr(runtime, "meta_call", fake_meta_call)
    response = client.post(
        "/api/dashboard-runtime/v2/execute",
        json={"plan": _cascading_plan(), "inputs": {"account_id": "123"}, "trigger": "on_change"},
    )
    assert response.status_code == 200
    assert calls[0]["path"] == "act_123/campaigns"
    assert response.json()["data"]["campaigns"] == [{"label": "Campaign One", "value": "cmp_1"}]


def test_declared_runtime_inputs_are_forwarded_without_duplicate_param_templates(monkeypatch):
    async def fake_token(request):
        return "token"

    calls = []

    def fake_meta_call(method, path, token, params=None):
        calls.append({"method": method, "path": path, "params": params})
        return {"data": [{"id": "cmp_1", "name": "Campaign One"}]}

    plan = {
        "id": "generated_filters",
        "nodes": [
            {
                "id": "get_campaigns",
                "connector": "meta",
                "operation": "list_campaigns",
                "params": {},
                "required_inputs": ["account_id"],
                "run_when": "on_change",
            }
        ],
    }
    monkeypatch.setattr(runtime, "resolve_access_token", fake_token)
    monkeypatch.setattr(runtime, "meta_call", fake_meta_call)

    response = client.post(
        "/api/dashboard-runtime/v2/execute",
        json={"plan": plan, "inputs": {"account_id": "123"}, "trigger": "on_change"},
    )

    assert response.status_code == 200
    assert calls[0]["path"] == "act_123/campaigns"


def test_entity_dropdowns_wait_for_their_direct_parent(monkeypatch):
    async def fake_token(request):
        return "token"

    calls = []

    def fake_meta_call(method, path, token, params=None):
        calls.append(path)
        return {"data": []}

    plan = {
        "id": "strict_cascading_filters",
        "nodes": [
            {
                "id": "campaigns",
                "connector": "meta",
                "operation": "list_campaigns",
                "required_inputs": ["account_id"],
                "run_when": "always",
            },
            {
                "id": "adsets",
                "connector": "meta",
                "operation": "list_adsets",
                "required_inputs": ["account_id", "campaign_id"],
                "run_when": "always",
            },
            {
                "id": "ads",
                "connector": "meta",
                "operation": "list_ads",
                "required_inputs": ["account_id", "adset_id"],
                "run_when": "always",
            },
        ],
    }
    monkeypatch.setattr(runtime, "resolve_access_token", fake_token)
    monkeypatch.setattr(runtime, "meta_call", fake_meta_call)

    response = client.post(
        "/api/dashboard-runtime/v2/execute",
        json={"plan": plan, "inputs": {"account_id": "123", "campaign_id": "all", "adset_id": "all"}, "trigger": "always"},
    )

    assert response.status_code == 200
    assert calls == ["act_123/campaigns"]
    statuses = {item["node_id"]: item for item in response.json()["node_status"]}
    assert statuses["adsets"]["missing_inputs"] == ["campaign_id"]
    assert statuses["ads"]["missing_inputs"] == ["adset_id"]


def test_meta_insights_query_uses_custom_time_range_and_drops_dashboard_only_filters():
    query = runtime._meta_insights_query(
        {
            "scope_id": "cmp_1",
            "account_id": "123",
            "campaign_id": "cmp_1",
            "analysis_level": "adset",
            "adset_id": "all",
            "ad_id": "all",
            "date_preset": "custom",
            "since": "2026-08-01",
            "until": "2026-08-20",
        }
    )

    assert query["time_range"] == '{"since":"2026-08-01","until":"2026-08-20"}'
    assert query["level"] == "adset"
    assert "account_id" not in query
    assert "campaign_id" not in query
    assert "date_preset" not in query


def test_all_adsets_insights_fall_back_to_campaign_scope(monkeypatch):
    async def fake_token(request):
        return "token"

    calls = []

    def fake_meta_call(method, path, token, params=None):
        calls.append({"path": path, "params": params})
        return {"data": []}

    plan = {
        "id": "insight_filters",
        "nodes": [
            {
                "id": "get_insights",
                "connector": "meta",
                "operation": "insights",
                "params": {},
                "required_inputs": [
                    "scope_id",
                    "account_id",
                    "campaign_id",
                    "analysis_level",
                    "adset_id",
                    "ad_id",
                    "date_preset",
                    "since",
                    "until",
                ],
                "run_when": "manual",
            }
        ],
    }
    monkeypatch.setattr(runtime, "resolve_access_token", fake_token)
    monkeypatch.setattr(runtime, "meta_call", fake_meta_call)
    response = client.post(
        "/api/dashboard-runtime/v2/execute",
        json={
            "plan": plan,
            "trigger": "manual",
            "inputs": {
                "scope_id": "",
                "account_id": "123",
                "campaign_id": "cmp_1",
                "analysis_level": "adset",
                "adset_id": "all",
                "ad_id": "all",
                "date_preset": "last_7d",
                "since": "all",
                "until": "all",
            },
        },
    )

    assert response.status_code == 200
    assert calls[0]["path"] == "cmp_1/insights"
    assert calls[0]["params"]["level"] == "adset"


def test_preview_token_is_bound_to_exact_plan(monkeypatch):
    async def fake_execute(plan, request, inputs=None, trigger="manual"):
        return {"plan_id": plan.id, "data": {"value": 12}, "nodes": {}, "node_status": []}

    monkeypatch.setattr(dashboard_runtime, "execute_plan", fake_execute)
    response = client.post(
        "/api/dashboard-runtime/v2/preview",
        json={"plan": _cascading_plan(), "inputs": {"account_id": "123"}, "trigger": "manual"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "awaiting_user_confirmation"
    plan = DashboardPlanValidateRequest.model_validate({"plan": _cascading_plan()}).plan
    assert runtime.verify_confirmation_token(body["confirmation_token"], plan)["plan_hash"]


def test_publishing_requires_preview_confirmation(monkeypatch):
    monkeypatch.setattr(dashboard_runtime, "_require_dashboard_owner", lambda request, dashboard_id, definition: "tenant_1")
    monkeypatch.setattr(
        dashboard_runtime.journey_dashboard_v7,
        "_get_dashboard_definition",
        lambda dashboard_id: {"dashboard_id": dashboard_id, "widgets": [], "runtime_queries": {}},
    )
    saved = {}

    def fake_save(definition, dashboard_id=None):
        saved.update(definition)
        return {"success": True, "url": f"/dashboards/custom/{dashboard_id}"}

    monkeypatch.setattr(dashboard_runtime.journey_dashboard_v7, "_save_dashboard_definition", fake_save)
    plan = DashboardPlanValidateRequest.model_validate({"plan": _cascading_plan()}).plan
    token = runtime.create_confirmation_token(plan, {"data": {"campaigns": []}})
    response = client.post(
        "/api/dashboard-runtime/v2/sections/publish",
        json={
            "dashboard_id": "dash_1",
            "section_id": "global_filters",
            "title": "Filters",
            "query_plan": _cascading_plan(),
            "presentation": {
                "type": "filters",
                "span": 12,
                "filters": [{"key": "account_id", "label": "Ad Account", "type": "select"}],
            },
            "confirmation_token": token,
        },
    )
    assert response.status_code == 200
    assert saved["runtime_queries"]["global_filters"]["nodes"]
    assert saved["widgets"][0]["data_query"] == "global_filters"
    assert saved["filters"] == [{"key": "account_id", "label": "Ad Account", "type": "select"}]


def test_funnel_publish_rejects_empty_backend_output(monkeypatch):
    plan_payload = _cascading_plan()
    plan_payload["output"] = {}
    plan = DashboardPlanValidateRequest.model_validate({"plan": plan_payload}).plan
    token = runtime.create_confirmation_token(plan, {"data": {}})

    response = client.post(
        "/api/dashboard-runtime/v2/sections/publish",
        json={
            "dashboard_id": "dash_1",
            "section_id": "journey_funnel",
            "title": "Customer Journey Funnel",
            "query_plan": plan_payload,
            "presentation": {"type": "funnel", "stages": [{"id": "clicks", "label": "Clicks"}]},
            "confirmation_token": token,
        },
    )

    assert response.status_code == 422
    assert "explicit query output" in response.json()["detail"]["message"]


def test_funnel_publish_rejects_incomplete_live_preview(monkeypatch):
    plan_payload = _funnel_plan()
    plan = DashboardPlanValidateRequest.model_validate({"plan": plan_payload}).plan
    token = runtime.create_confirmation_token(
        plan,
        {
            "status": "success",
            "data": {"stages": [{"id": "clicks"}, {"id": "register"}], "complete": False},
            "node_status": [],
        },
    )

    response = client.post(
        "/api/dashboard-runtime/v2/sections/publish",
        json={
            "dashboard_id": "dash_1",
            "section_id": "journey_funnel",
            "title": "Customer Journey Funnel",
            "query_plan": plan_payload,
            "presentation": {
                "type": "funnel",
                "stages": [
                    {"id": "external_clicks", "label": "External link clicks", "source": "meta"},
                    {"id": "register_page", "label": "Register Page", "source": "meta_event"},
                ],
            },
            "confirmation_token": token,
        },
    )

    assert response.status_code == 409
    assert "did not contain a complete funnel" in response.json()["detail"]["message"]


def test_funnel_publish_rejects_sign_up_ref_as_event():
    plan_payload = _funnel_plan()
    plan_payload["nodes"][0]["params"]["stages"][1]["value"] = {
        "from": "ga4",
        "rows_path": "normalized_rows",
        "where": {"event_name": "sign_up_ref"},
    }
    plan_payload["nodes"].append(
        {
            "id": "ga4",
            "connector": "ga4",
            "operation": "report",
            "params": {"tenant_id": "tenant_1", "metrics": ["eventCount"]},
        }
    )
    plan_payload["nodes"][0]["depends_on"].append("ga4")
    plan = DashboardPlanValidateRequest.model_validate({"plan": plan_payload}).plan
    token = runtime.create_confirmation_token(
        plan,
        {"status": "success", "data": {"stages": [{}, {}], "complete": True}, "node_status": []},
    )

    response = client.post(
        "/api/dashboard-runtime/v2/sections/publish",
        json={
            "dashboard_id": "dash_1",
            "section_id": "journey_funnel",
            "title": "Customer Journey Funnel",
            "query_plan": plan_payload,
            "presentation": {
                "type": "funnel",
                "stages": [
                    {"id": "external_clicks", "label": "Clicks", "source": "meta"},
                    {"id": "register_page", "label": "Register", "source": "ga4"},
                ],
            },
            "confirmation_token": token,
        },
    )

    assert response.status_code == 422
    assert "attribution dimension" in response.json()["detail"]["message"]
