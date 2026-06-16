from fastapi.testclient import TestClient

from app.analytics.dashboard_engine import build_fallback_funnel, stage_detail
from app.main import app


client = TestClient(app)


def test_journey_dashboard_page_renders_runtime():
    response = client.get("/journey-dashboard/v7")

    assert response.status_code == 200
    assert "Customer Journey Intelligence" in response.text
    assert "Conversion Path" in response.text
    assert "Comparison Lab" in response.text


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


def test_connector_registry_exposes_metric_dictionary():
    response = client.get("/api/dashboard-runtime/connectors")

    assert response.status_code == 200
    data = response.json()
    assert "meta" in data["connectors"]
    assert data["metrics"]["register_page"]["source"] == "meta_event"


def test_fallback_funnel_calculates_transition_and_costs():
    funnel = build_fallback_funnel()
    register = next(stage for stage in funnel["stages"] if stage["id"] == "register_page")

    assert register["transition_rate"] is not None
    assert register["drop_rate"] is not None
    assert register["cost"] > 0
