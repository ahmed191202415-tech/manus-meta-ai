"""Official SDK Google Ads campaign clone preview safety tests.

All provider calls are mocked; no production campaigns or OAuth secrets involved.
"""
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app, openapi_gpt_schema
from app.core import google_ads_clone as clone
from app.core import google_ads_gateway as gateway


def fake_sdk_search(tenant, cid, query, manager_id=None, limit=250):
    assert tenant == "sample-tenant"
    assert cid == "3333735582"
    assert manager_id is None
    if "FROM customer" in query:
        return {"rows": [{"customer": {"id": "3333735582", "currencyCode": "EGP"}}]}
    if "FROM campaign WHERE campaign.name" in query:
        return {"rows": []}
    if "FROM campaign WHERE campaign.id" in query:
        return {"rows": [{"campaign": {
            "id": "24387253876", "name": "Sales-Search-1",
            "advertisingChannelType": "SEARCH",
        }}]}
    if "FROM ad_group WHERE" in query:
        return {"rows": [{"adGroup": {
            "id": "204483944314", "name": "crm",
            "campaign": "customers/3333735582/campaigns/24387253876",
        }}]}
    if "FROM ad_group_criterion" in query and "type = 'KEYWORD'" in query:
        return {"rows": [
            {"adGroupCriterion": {"status": "ENABLED", "keyword": {
                "text": "crm", "matchType": "PHRASE",
            }}} for _ in range(45)
        ]}
    if "FROM ad_group_ad" in query:
        return {"rows": [{"adGroupAd": {"ad": {"id": "123", "type": "RESPONSIVE_SEARCH_AD"}}}]}
    return {"rows": []}


def request_body():
    return {
        "action": "clone_campaign",
        "customer_id": "3333735582",
        "source_campaign_id": "24387253876",
        "new_campaign_name": "Sales-Search-CRM",
        "keep_ad_group_ids": ["204483944314"],
        "daily_budget_micros": 800000000,
        "status": "PAUSED", "dry_run": True,
    }


def test_clone_preview_one_command_uses_official_sdk_without_write(monkeypatch):
    monkeypatch.setattr(gateway, "_required_app_identity", lambda _: {"tenant_id": "sample-tenant"})
    monkeypatch.setattr(clone, "sdk_search", fake_sdk_search)
    monkeypatch.setattr(gateway, "_api", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Cannot write")))
    response = TestClient(app).post("/tools/intent", json={
        "request": "google_ads " + __import__("json").dumps(request_body())
    })
    assert response.status_code == 200, response.text
    j = response.json()
    assert j["action"] == "clone_campaign"
    assert j["mode"] == "DRY_RUN"
    assert j["no_changes_applied"] is True
    assert j["verified_source_identity"] is True
    assert j["proposed"]["status"] == "PAUSED"
    assert j["proposed"]["daily_budget_egp"] == 800
    assert j["sections"]["keywords"]["count"] == 45
    assert j["ready_for_execution"] is False
    assert len(openapi_gpt_schema()["paths"]) == 28


def test_clone_disallows_live_write_and_wrong_status(monkeypatch):
    monkeypatch.setattr(clone, "sdk_search", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Unexpected read")))
    for update in [
        {"dry_run": False}, {"dry_run": None}, {"status": "ENABLED"},
        {"keep_ad_group_ids": ["204483944314", "999"]},
        {"daily_budget_micros": "800000000"},
        {"source_campaign_id": "24387253876; DROP"},
    ]:
        d = {**request_body(), **update}
        try:
            clone.preview_clone_campaign("sample-tenant", d)
        except HTTPException as err:
            assert err.status_code in (403, 422)
        else:
            raise AssertionError("Unsafe action permitted: " + repr(update))


def test_partial_provider_error_is_visible_without_mutation(monkeypatch):
    def fail_ads(*a, **k):
        if "FROM ad_group_ad" in a[2]:
            raise HTTPException(502, {
                "origin": "google_ads_official_sdk",
                "google_ads_error_code": "CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION"
            })
        return fake_sdk_search(*a, **k)
    monkeypatch.setattr(clone, "sdk_search", fail_ads)
    result = clone.preview_clone_campaign("sample-tenant", request_body())
    assert result["sections"]["ads"]["error"]["code"] == "CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION"
    assert "READ_FAILURES" in result["blockers"]
    assert result["ready_for_execution"] is False


def test_duplicate_target_name_is_explicit_blocker(monkeypatch):
    def duplicate(*a, **k):
        if "FROM campaign WHERE campaign.name" in a[2]:
            return {"rows": [{"campaign": {"id": "999", "name": "Sales-Search-CRM"}}]}
        return fake_sdk_search(*a, **k)
    monkeypatch.setattr(clone, "sdk_search", duplicate)
    result = clone.preview_clone_campaign("sample-tenant", request_body())
    assert "DESTINATION_CAMPAIGN_NAME_ALREADY_EXISTS" in result["blockers"]
    assert result["ready_for_execution"] is False
