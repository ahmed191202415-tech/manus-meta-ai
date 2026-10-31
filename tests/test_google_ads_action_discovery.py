"""Live Google Ads account/campaign discovery through the pre-existing GPT Actions endpoint."""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import gpt_tools
from app.core import google_ads_gateway as gateway
from app.core import google_ads_discovery as discovery
from app.main import openapi_gpt_schema
from app.schemas.gpt_tool_requests import IntentToolRequest


def test_original_action_schema_still_unchanged():
    paths = openapi_gpt_schema()["paths"]
    assert len(paths) == 28
    assert "/tools/intent" in paths
    assert "/tools/google_ads" not in paths


def test_connection_status_does_live_api_read(monkeypatch):
    calls = []
    monkeypatch.setattr(gateway, "get_active_google_connection_for_tenant", lambda tenant: {
        "connection_mode": "oauth", "scopes": gateway.ADS_SCOPE
    })
    def fake_api(*args, **kwargs):
        calls.append(args)
        return {"resourceNames":["customers/1234567890"]}
    monkeypatch.setattr(gateway, "_api", fake_api)
    result = gateway.execute_google_ads_command({"action":"status"}, {"tenant_id":"t"})
    assert result["connected"] is True
    assert result["google_ads_api_ok"] is True
    assert result["verified_account_ids"] == ["1234567890"]
    assert len(calls) == 1


def test_status_reports_api_failure_not_false_positive(monkeypatch):
    monkeypatch.setattr(gateway, "get_active_google_connection_for_tenant", lambda tenant: {
        "connection_mode":"oauth", "scopes":gateway.ADS_SCOPE
    })
    monkeypatch.setattr(gateway, "_api", lambda *a, **k: (_ for _ in ()).throw(HTTPException(403, "PERMISSION_DENIED")))
    status = gateway.execute_google_ads_command({"action":"status"}, {"tenant_id":"t"})
    assert status["oauth_scope_connected"] is True
    assert status["google_ads_api_ok"] is False
    assert status["read_error_http_status"] == 403


def test_named_campaign_read_discovers_ids_and_ad_groups(monkeypatch):
    def fake_api(tenant, method, path, body=None, **kwargs):
        assert path == "/customers:listAccessibleCustomers"
        return {"resourceNames":["customers/1234567890"]}
    def fake_read(query, tenant, customer, manager_id=None, limit=100):
        if "FROM customer LIMIT" in query:
            return {"rows":[{"customer":{"id":customer,"descriptiveName":"Test Account","currencyCode":"EGP","manager":False}}]}
        if "FROM campaign" in query:
            assert "Sales-Search-1" in query
            return {"rows":[{
                "campaign":{"id":"987","name":"Sales-Search-1","status":"ENABLED",
                            "campaignBudget":"customers/1234567890/campaignBudgets/3"},
                "campaignBudget":{"amountMicros":"250000000","explicitlyShared":False},
            }]}
        if "FROM ad_group" in query:
            assert "campaign.id = 987" in query
            return {"rows":[{"adGroup":{"id":"555","name":"crm","status":"ENABLED"},
                             "metrics":{"costMicros":"10000000"}}]}
        raise AssertionError(query)
    monkeypatch.setattr(gateway, "_api", fake_api)
    monkeypatch.setattr(gateway, "_read", fake_read)
    result=discovery.inspect_campaign_live("t", "Sales-Search-1")
    assert result["verified_by_google_api"] is True
    assert result["campaigns"][0]["campaign_id"] == "987"
    assert result["campaigns"][0]["ad_groups"][0]["name"] == "crm"
    assert result["campaigns"][0]["currency"] == "EGP"
    assert "does not change" in result["note"].lower() or "does not change" in result["note"]


def test_natural_request_routes_to_live_discovery_without_new_schema(monkeypatch):
    monkeypatch.setattr(gateway, "_required_app_identity", lambda req: {"tenant_id":"tenant-a"})
    seen=[]
    def fake_execute(command, identity):
        seen.append(command)
        return {"ok":True,"action":command["action"]}
    monkeypatch.setattr(gateway, "execute_google_ads_command", fake_execute)
    body = IntentToolRequest(request="Google Ads حلل Sales-Search-1 وشوف crm بميزانية 800 جنيه")
    result = asyncio.run(gpt_tools.intent_tool(body, request=SimpleNamespace()))
    assert result["action"] == "inspect_campaign"
    assert seen[0]["campaign_name"] == "Sales-Search-1"
    assert not any(k in seen[0] for k in ("operations","confirmation_phrase"))


def test_no_read_token_or_campaign_name_guessing():
    with pytest.raises(HTTPException):
        discovery.inspect_campaign_live("t", "Campaign'; DELETE FROM campaign;")
