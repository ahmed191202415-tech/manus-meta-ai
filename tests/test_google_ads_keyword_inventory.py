"""Regression tests for the isolated keyword inventory reader (no live Ads writes)."""
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from app.core import google_ads_gateway as gateway
from app.core import google_ads_keyword_inventory as inv

CUSTOMER = "3333735582"
CAMPAIGN = "24412747386"
GROUP = "201563783253"
PARAMS = {"customer_id": CUSTOMER, "campaign_id": CAMPAIGN, "ad_group_id": GROUP}

def inventory_row(campaign=CAMPAIGN, group=GROUP, criterion_id="101"):
    return {
        "campaign": {"id": campaign}, "adGroup": {"id": group},
        "adGroupCriterion": {
            "criterionId": criterion_id, "status": "ENABLED",
            "keyword": {"text": "برنامج crm", "matchType": "PHRASE"},
            "qualityInfo": {"qualityScore": 8, "searchPredictedCtr": "ABOVE_AVERAGE"},
        },
    }

def performance_row(campaign=CAMPAIGN, group=GROUP, criterion_id="101"):
    return {
        "campaign": {"id": campaign}, "adGroup": {"id": group},
        "adGroupCriterion": {"criterionId": criterion_id},
        "metrics": {"impressions": "90", "clicks": "9", "costMicros": "2000000", "conversions": "2"},
    }

def test_full_inventory_and_performance_join(monkeypatch):
    queries = []
    def mocked_api(tenant, method, path, payload, **kwargs):
        queries.append(payload["query"])
        return {"results": [inventory_row()] if "FROM ad_group_criterion" in payload["query"] else [performance_row()]}
    monkeypatch.setattr(gateway, "_api", mocked_api)
    result = inv.read_keyword_inventory("tenant-123", PARAMS)
    assert result["count"] == 1
    assert result["scope_verified"] and result["inventory_complete"]
    assert result["keywords"][0]["keyword"] == "برنامج crm"
    assert result["keywords"][0]["quality_score"] == 8
    assert result["keywords"][0]["clicks"] == 9
    assert "FROM ad_group_criterion WHERE" in queries[0]
    assert "FROM keyword_view WHERE" in queries[1]
    for q in queries:
        assert "campaign.id = " + CAMPAIGN in q
        assert "ad_group.id = " + GROUP in q
        assert "ad_group_criterion.status = ENABLED" in q
    assert "segments.date" not in queries[0]
    assert "segments.date DURING LAST_30_DAYS" in queries[1]

def test_no_impressions_still_returns_keyword(monkeypatch):
    monkeypatch.setattr(gateway, "_api", lambda tenant, method, path, payload, **kwargs: {
        "results": [inventory_row()] if "FROM ad_group_criterion" in payload["query"] else []
    })
    result = inv.read_keyword_inventory("tenant-123", PARAMS)
    assert result["count"] == 1
    assert result["keywords"][0]["clicks"] == 0

@pytest.mark.parametrize("row_type", ["inventory", "performance"])
def test_wrong_ad_group_never_leaks_rows(monkeypatch, row_type):
    def mocked_api(tenant, method, path, payload, **kwargs):
        if "FROM ad_group_criterion" in payload["query"]:
            return {"results": [inventory_row(group="204483944314" if row_type == "inventory" else GROUP)]}
        return {"results": [performance_row(group="204483944314")]}
    monkeypatch.setattr(gateway, "_api", mocked_api)
    with pytest.raises(HTTPException) as e:
        inv.read_keyword_inventory("tenant-123", PARAMS)
    assert e.value.status_code == 502

def test_rejects_missing_scope_and_injection():
    for args in [
        {"customer_id": CUSTOMER, "campaign_id": CAMPAIGN},
        {**PARAMS, "ad_group_id": "201563783253 OR 1=1"}
    ]:
        with pytest.raises(HTTPException) as e:
            inv.read_keyword_inventory("tenant-123", args)
        assert e.value.status_code == 422

def test_supports_page_tokens_and_combines_all_rows(monkeypatch):
    page = []
    def mocked_api(tenant, method, path, payload, **kwargs):
        if "FROM keyword_view" in payload["query"]:
            return {"results": []}
        page.append(payload.get("pageToken"))
        if len(page) == 1:
            return {"results": [inventory_row(criterion_id="101")], "nextPageToken": "next-token"}
        return {"results": [inventory_row(criterion_id="102")]}
    monkeypatch.setattr(gateway, "_api", mocked_api)
    result = inv.read_keyword_inventory("tenant-123", PARAMS)
    assert result["count"] == 2
    assert page == [None, "next-token"]

def test_explicit_json_command_only_does_not_change_natural_parser():
    message = (
        'google_ads {"action":"keyword_inventory","customer_id":"' + CUSTOMER +
        '","campaign_id":"' + CAMPAIGN + '","ad_group_id":"' + GROUP + '"}'
    )
    command = gateway.parse_google_ads_request(SimpleNamespace(request=message, meta_account_id=None))
    assert command["action"] == "keyword_inventory"
    assert gateway.parse_google_ads_request(SimpleNamespace(
        request="google_ads افحص Sales-Search-1", meta_account_id=None
    ))["action"] == "inspect_campaign"


def test_api_search_omits_unsupported_page_size_in_both_queries(monkeypatch):
    payloads = []
    def mocked_api(tenant, method, path, payload, **kwargs):
        assert method == "POST"
        assert path.endswith("/googleAds:search")
        assert "pageSize" not in payload
        assert "page_size" not in payload
        payloads.append(dict(payload))
        return {"results": [inventory_row()] if "FROM ad_group_criterion" in payload["query"] else [performance_row()]}
    monkeypatch.setattr(gateway, "_api", mocked_api)
    result = inv.read_keyword_inventory("tenant-123", PARAMS)
    assert result["count"] == 1
    assert len(payloads) == 2
    assert all(set(payload) == {"query"} for payload in payloads)


def test_pagination_sends_page_token_without_page_size(monkeypatch):
    requests = []
    def mocked_api(tenant, method, path, payload, **kwargs):
        requests.append(dict(payload))
        assert "pageSize" not in payload
        if "FROM keyword_view" in payload["query"]:
            return {"results": []}
        if "pageToken" not in payload:
            return {"results": [inventory_row(criterion_id="101")], "nextPageToken": "next-token"}
        assert payload["pageToken"] == "next-token"
        return {"results": [inventory_row(criterion_id="102")]}
    monkeypatch.setattr(gateway, "_api", mocked_api)
    result = inv.read_keyword_inventory("tenant-123", PARAMS)
    assert result["count"] == 2
    assert len(requests) == 3
    assert set(requests[0]) == {"query"}
    assert set(requests[1]) == {"query", "pageToken"}
