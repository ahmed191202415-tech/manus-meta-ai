from fastapi.testclient import TestClient

from app.api import dashboard_runtime
from app.core import dashboard_runtime as runtime
from app.main import app
from app.schemas.dashboard_runtime_requests import DashboardPlanValidateRequest
from app.core.dashboard_plan import resolve_templates
from app.core.dashboard_transforms import build_options, safe_formula


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
            "presentation": {"type": "filters", "span": 12},
            "confirmation_token": token,
        },
    )
    assert response.status_code == 200
    assert saved["runtime_queries"]["global_filters"]["nodes"]
    assert saved["widgets"][0]["data_query"] == "global_filters"
