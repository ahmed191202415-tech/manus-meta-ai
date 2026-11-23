"""Account-level diagnostics for real Google Ads API error enums (mocked).

No live OAuth calls or advertising changes.
"""
from fastapi import HTTPException
from app.core import google_ads_gateway as gateway
from app.core import google_ads_discovery as discovery


def _read_with_errors(query, tenant, customer_id, manager_id=None, limit=100):
    errors = {
        "7030468211": "CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION",
        "3333735582": "CUSTOMER_NOT_ENABLED",
    }
    code = errors[customer_id]
    raise HTTPException(403, {
        "origin": "google_ads_api",
        "http_status": 403,
        "api_status": "PERMISSION_DENIED",
        "google_ads_error_code": code,
        "message": "Google Ads API rejected the request.",
        "next_step": "Resolve " + code,
    })


def test_list_accounts_preserves_account_specific_codes(monkeypatch):
    monkeypatch.setattr(gateway, "_api", lambda *args, **kwargs: {
        "resourceNames": ["customers/7030468211", "customers/3333735582"]
    })
    monkeypatch.setattr(gateway, "_read", _read_with_errors)
    result = discovery.list_accounts_live("fake-tenant")
    assert result["verified_by_google_api"] is True
    assert result["account_list_verified"] is True
    assert result["account_details_verified"] == 0
    errors = {
        item["customer_id"]: item["details_error"]["google_ads_error_code"]
        for item in result["accounts"]
    }
    assert errors == {
        "7030468211": "CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION",
        "3333735582": "CUSTOMER_NOT_ENABLED",
    }
    assert "Resolve" in result["next_step"]
    assert all(item["details_unavailable"] for item in result["accounts"])


def test_inspect_campaign_never_claims_verified_campaign_on_403(monkeypatch):
    monkeypatch.setattr(gateway, "_api", lambda *args, **kwargs: {
        "resourceNames": ["customers/7030468211", "customers/3333735582"]
    })
    monkeypatch.setattr(gateway, "_read", _read_with_errors)
    result = discovery.inspect_campaign_live("fake-tenant", "Sales-Search-1")
    assert result["campaign_data_verified"] is False
    assert result["campaigns"] == []
    assert result["accounts_checked"] == 0
    assert any(x["stage"] == "account_details" for x in result["account_errors"])
    assert any(x["stage"] == "campaign_lookup" for x in result["account_errors"])
    assert {x["google_ads_error_code"] for x in result["account_errors"]} == {
        "CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION", "CUSTOMER_NOT_ENABLED"
    }


def test_error_details_are_safe_and_stable():
    exc = HTTPException(403, "Untrusted upstream string")
    cleaned = discovery._safe_google_ads_error(exc)
    assert cleaned["origin"] == "unknown"
    assert cleaned["google_ads_error_code"] == "UNSPECIFIED"
    assert "Untrusted" not in str(cleaned)
