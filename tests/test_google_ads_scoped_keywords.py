"""Scoped Google Ads keyword reading safety tests.

Mocks Google Ads data; never touches a real advertising account.
"""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core import google_ads_gateway as ads


CID = "3333735582"
CAMPAIGN = "24412747386"
GROUP = "201563783253"


def parse(request):
    return ads.parse_google_ads_request(SimpleNamespace(
        request=request, meta_account_id=None, campaign_name=None
    ))


def _row(campaign=CAMPAIGN, group=GROUP):
    return {
        "campaign": {"id": campaign, "name": "Sales-Search-crm"},
        "adGroup": {"id": group, "name": "crm"},
        "adGroupCriterion": {"keyword": {"text": "crm system"}},
        "metrics": {"clicks": "3", "impressions": "15"},
    }


def test_natural_request_uses_scoped_keyword_action():
    command = parse(
        "google_ads اعرض الكلمات المفتاحية للحملة رقم " + CAMPAIGN +
        " المجموعة الإعلانية رقم " + GROUP + " customer_id " + CID
    )
    assert command == {
        "action": "scoped_keywords", "customer_id": CID,
        "campaign_id": CAMPAIGN, "ad_group_id": GROUP,
    }


def test_explicit_gaql_keyword_action_retained():
    command = parse(
        'google_ads {"action":"query","customer_id":"' + CID +
        '","query":"SELECT campaign.id, ad_group.id, '
        'ad_group_criterion.keyword.text FROM keyword_view '
        'WHERE campaign.id = ' + CAMPAIGN + ' AND ad_group.id = ' + GROUP + '"}'
    )
    assert command["action"] == "query"


def test_scoped_keyword_query_filters_both_ids_and_verifies_rows(monkeypatch):
    captured = []
    def mock_read(query, tenant, customer_id, manager_id, limit):
        captured.append((query, tenant, customer_id))
        return {"rows": [_row()], "count": 1, "truncated": False}
    monkeypatch.setattr(ads, "_read", mock_read)
    result = ads.execute_google_ads_command({
        "action": "scoped_keywords", "customer_id": CID,
        "campaign_id": CAMPAIGN, "ad_group_id": GROUP,
    }, {"tenant_id": "test-tenant"})
    assert result["scope_verified"] is True
    assert result["count"] == 1
    assert "campaign.id = " + CAMPAIGN in captured[0][0]
    assert "ad_group.id = " + GROUP in captured[0][0]
    assert captured[0][2] == CID


@pytest.mark.parametrize("wrong_campaign,wrong_group", [
    ("24387253876", GROUP), (CAMPAIGN, "204483944314"),
    (None, GROUP), (CAMPAIGN, None),
])
def test_scoped_keyword_read_rejects_other_or_missing_ids(monkeypatch, wrong_campaign, wrong_group):
    monkeypatch.setattr(ads, "_read", lambda *args: {
        "rows": [_row(wrong_campaign, wrong_group)], "count": 1, "truncated": False
    })
    with pytest.raises(HTTPException) as error:
        ads.execute_google_ads_command({
            "action": "scoped_keywords", "customer_id": CID,
            "campaign_id": CAMPAIGN, "ad_group_id": GROUP,
        }, {"tenant_id": "test-tenant"})
    assert error.value.status_code == 502


def test_report_keywords_uses_campaign_filter_not_global_account(monkeypatch):
    captured = []
    monkeypatch.setattr(ads, "_read", lambda query, *args: (
        captured.append(query) or {"rows": [_row()], "count": 1, "truncated": False}
    ))
    result = ads._report("test-tenant", {
        "customer_id": CID, "report": "keywords", "campaign_id": CAMPAIGN,
        "date_range": "LAST_30_DAYS",
    })
    assert "campaign.id = " + CAMPAIGN in captured[0]
    assert "segments.date DURING LAST_30_DAYS" in captured[0]
    assert result["scope_verified"] is True


def test_raw_gaql_mismatched_ids_withheld(monkeypatch):
    monkeypatch.setattr(ads, "_read", lambda *args: {
        "rows": [_row("24387253876", GROUP)], "count": 1, "truncated": False
    })
    with pytest.raises(HTTPException) as error:
        ads.execute_google_ads_command({
            "action": "query", "customer_id": CID,
            "query": (
                "SELECT campaign.id, ad_group.id, ad_group_criterion.keyword.text "
                "FROM keyword_view WHERE campaign.id = " + CAMPAIGN +
                " AND ad_group.id = " + GROUP
            ),
        }, {"tenant_id": "test-tenant"})
    assert error.value.status_code == 502


def test_scope_ids_are_required_and_validated():
    with pytest.raises(HTTPException) as missing:
        ads.execute_google_ads_command({
            "action": "scoped_keywords", "customer_id": CID, "campaign_id": CAMPAIGN,
        }, {"tenant_id": "test-tenant"})
    assert missing.value.status_code == 422
    with pytest.raises(HTTPException) as invalid:
        ads.execute_google_ads_command({
            "action": "scoped_keywords", "customer_id": CID,
            "campaign_id": "24412747386 OR TRUE", "ad_group_id": GROUP,
        }, {"tenant_id": "test-tenant"})
    assert invalid.value.status_code == 422


def test_raw_gaql_adds_ids_to_select_before_verifying(monkeypatch):
    queries = []
    def mock_read(query, *args):
        queries.append(query)
        return {"rows": [_row()], "count": 1, "truncated": False}
    monkeypatch.setattr(ads, "_read", mock_read)
    result = ads.execute_google_ads_command({
        "action": "query", "customer_id": CID,
        "query": (
            "SELECT ad_group_criterion.keyword.text, metrics.clicks "
            "FROM keyword_view WHERE campaign.id = " + CAMPAIGN +
            " AND ad_group.id = " + GROUP
        ),
    }, {"tenant_id": "test-tenant"})
    assert result["scope_verified"] is True
    assert "SELECT campaign.id, ad_group.id, " in queries[0]


def test_named_campaign_without_id_uses_discovery_not_account_wide_report():
    command = parse(
        "google_ads اعرض الكلمات المفتاحية لحملة Sales-Search-crm customer_id " + CID
    )
    assert command["action"] == "inspect_campaign"
    assert command["campaign_name"] == "Sales-Search-crm"
