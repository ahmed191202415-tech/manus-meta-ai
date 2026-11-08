from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from app.core import google_ads_gateway as ads

CUSTOMER = "3333735582"
CAMPAIGN = "24412747386"
GROUP = "201563783253"


def parse(message, account=None):
    return ads.parse_google_ads_request(SimpleNamespace(
        request=message, campaign_name=None, meta_account_id=account,
    ))


@pytest.mark.parametrize("message", [
    "google_ads اقرأ الكلمات المفتاحية للحملة رقم 24412747386 المجموعة الإعلانية رقم 201563783253 customer_id 3333735582 Sales-Search-crm",
    "google ads keywords campaign_id=24412747386 ad_group_id=201563783253 customer_id=3333735582 Sales-Search-crm",
    "جوجل ادز اعرض Quality Score لحملة رقم 24412747386 للمجموعة رقم 201563783253 customer_id 3333735582",
])
def test_natural_keyword_read_is_not_inspect_campaign(message):
    command = parse(message)
    assert command == {
        "action": "keyword_inventory",
        "customer_id": CUSTOMER,
        "campaign_id": CAMPAIGN,
        "ad_group_id": GROUP,
    }


def test_keyword_request_with_missing_scope_fails_closed():
    result = parse("google_ads كلمات حملة Sales-Search-crm customer_id 3333735582")
    assert result["action"] == "keyword_inventory"
    assert result["campaign_id"] is None
    with pytest.raises(HTTPException) as exc:
        ads.execute_google_ads_command(result, {"tenant_id": "test"})
    assert exc.value.status_code == 422


def test_explicit_json_stays_unchanged():
    command = parse('google_ads {"action":"keyword_inventory","customer_id":"' + CUSTOMER
                    + '","campaign_id":"' + CAMPAIGN + '","ad_group_id":"' + GROUP + '"}')
    assert command["action"] == "keyword_inventory"
    assert command["ad_group_id"] == GROUP


def test_campaign_inspection_without_keyword_request_is_unchanged():
    result = parse("google_ads افحص Sales-Search-crm customer_id 3333735582")
    assert result["action"] == "inspect_campaign"


def test_ambiguous_keyword_request_never_falls_back_to_account_report():
    result = parse("google_ads اعرض الكلمات لحملة Sales-Search-crm")
    assert result["action"] == "keyword_inventory"
    assert result["customer_id"] is None


def test_body_account_id_is_respected_when_customer_not_written():
    result = parse("google_ads keywords campaign_id=24412747386 ad_group_id=201563783253", CUSTOMER)
    assert result["customer_id"] == CUSTOMER
