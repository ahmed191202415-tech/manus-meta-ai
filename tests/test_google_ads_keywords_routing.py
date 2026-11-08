"""Regression coverage for keyword requests that name a campaign.

Pure parser tests: no Google Ads API calls, credentials, or mutations.
"""
from types import SimpleNamespace

from app.core.google_ads_gateway import parse_google_ads_request


def parse(message, account=None):
    return parse_google_ads_request(SimpleNamespace(
        request=message, meta_account_id=account, campaign_name=None
    ))


def test_keyword_report_named_campaign_id_uses_keyword_view():
    command = parse(
        "google_ads اعرض الكلمات المفتاحية للحملة رقم 24387253876 "
        "customer_id 3333735582 Sales-Search-1"
    )
    assert command["action"] == "query"
    assert command["customer_id"] == "3333735582"
    assert "FROM keyword_view" in command["query"]
    assert "campaign.id = 24387253876" in command["query"]


def test_explicit_gaql_does_not_become_inspect_campaign():
    command = parse(
        "google_ads account_id 3333735582 SELECT "
        "ad_group_criterion.keyword.text FROM keyword_view "
        "WHERE campaign.id = 24387253876"
    )
    assert command["action"] == "query"
    assert "FROM keyword_view" in command["query"]


def test_keyword_request_without_account_does_not_treat_campaign_as_account():
    command = parse(
        "google_ads اعرض الكلمات المفتاحية للحملة رقم 24387253876 Sales-Search-1"
    )
    assert command["action"] == "list_accounts"


def test_plain_campaign_inspection_is_unchanged():
    command = parse("google_ads inspect_campaign Sales-Search-1")
    assert command["action"] == "inspect_campaign"


def test_explicit_json_query_is_unchanged():
    command = parse(
        'google_ads {"action":"query","customer_id":"3333735582",'
        '"query":"SELECT ad_group_criterion.keyword.text FROM keyword_view '
        'WHERE campaign.id = 24387253876"}'
    )
    assert command["action"] == "query"
    assert command["customer_id"] == "3333735582"
