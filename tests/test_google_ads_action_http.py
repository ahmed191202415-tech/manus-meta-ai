"""HTTP-level checks for the existing ChatGPT Action (Meta routes unchanged).

These tests stub the identity and Google data layer; they never touch live Ads.
"""
import logging

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app, openapi_gpt_schema
from app.core import google_ads_gateway as ads
from app.core import google_ads_discovery as discovery


def test_existing_gpt_action_ping_is_called_and_traceable(monkeypatch, caplog):
    monkeypatch.setattr(ads, "_required_app_identity", lambda request: {"tenant_id": "mock-tenant"})
    with caplog.at_level(logging.WARNING, logger="ads.google_action"):
        response = TestClient(app).post(
            "/tools/intent",
            json={"request": 'google_ads {"action":"ping"}'},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["intent_reached"] is True
    assert body["google_api_called"] is False
    assert body["action_diagnostics"]["route"] == "/tools/intent"
    assert body["action_diagnostics"]["handler"] == "google_ads"
    assert body["action_diagnostics"]["executed"] is True
    assert body["action_diagnostics"]["request_id"]
    assert "google_ads_intent received" in caplog.text
    assert "google_ads_intent completed" in caplog.text
    assert "mock-tenant" not in caplog.text


def test_named_campaign_http_path_returns_google_ads_json(monkeypatch):
    monkeypatch.setattr(ads, "_required_app_identity", lambda request: {"tenant_id": "mock-tenant"})
    monkeypatch.setattr(discovery, "inspect_campaign_live", lambda *args, **kwargs: {
        "provider": "google_ads",
        "action": "inspect_campaign",
        "verified_by_google_api": True,
        "campaigns": [{"campaign_id": "987", "ad_groups": [{"id": "555", "name": "crm"}]}],
    })
    response = TestClient(app).post(
        "/tools/intent",
        json={"request": "google_ads inspect_campaign Sales-Search-1"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["campaigns"][0]["campaign_id"] == "987"
    assert body["campaigns"][0]["ad_groups"][0]["name"] == "crm"
    assert body["action_diagnostics"]["data_source"] == "Google Ads API"


def test_google_ads_is_denied_without_authorized_gpt_session(monkeypatch):
    def deny(_):
        raise HTTPException(status_code=401, detail="Unauthorized")
    monkeypatch.setattr(ads, "_required_app_identity", deny)
    response = TestClient(app).post(
        "/tools/intent",
        json={"request": "google_ads ping"},
    )
    assert response.status_code == 401


def test_legacy_schema_preserves_28_actions():
    schema = openapi_gpt_schema()
    assert len(schema["paths"]) == 28
    assert "/tools/intent" in schema["paths"]
    assert schema["paths"]["/tools/intent"]["post"]["operationId"] == "intent_tool_tools_intent_post"
