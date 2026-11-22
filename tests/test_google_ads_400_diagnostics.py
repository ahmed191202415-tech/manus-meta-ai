"""Safe Google Ads 400 diagnostics preserve upstream error cause and request ID."""
import pytest
from fastapi import HTTPException
from app.core import google_ads_gateway as ads


class FakeResponse:
    status_code = 400
    headers = {"request-id": "D4X1I1y0EhwTPh4Nu1G11Q"}
    def __init__(self, body):
        self.body = body
    def json(self):
        return self.body


def invoke(monkeypatch, error):
    monkeypatch.setattr(ads, "_credentials", lambda tenant: {"access_token": "test"})
    monkeypatch.setattr(ads, "_headers", lambda credentials, manager_id=None: {})
    monkeypatch.setattr(ads.requests, "request", lambda *a, **kw: FakeResponse({"error": error}))
    with pytest.raises(HTTPException) as exc:
        ads._api("tenant", "POST", "/customers/3333735582/googleAds:searchStream", {"query": "SELECT campaign.id FROM campaign"})
    return exc.value


def test_gaql_error_is_exposed_without_raw_provider_message(monkeypatch):
    err = invoke(monkeypatch, {
        "code": 3, "message": "Request contains invalid argument", "status": "INVALID_ARGUMENT",
        "details": [{"@type": "type.googleapis.com/google.ads.googleads.v25.errors.GoogleAdsFailure",
                     "errors": [{"errorCode": {"queryError": "UNRECOGNIZED_FIELD"},
                                 "message": "Unknown field <secret>",
                                 "location": {"fieldPathElements": [{"fieldName": "query"}]}}]}],
    })
    assert err.status_code == 400
    assert err.detail["google_ads_error_code"] == "UNRECOGNIZED_FIELD"
    assert err.detail["google_ads_error_field"] == "query"
    assert err.detail["google_request_id"] == "D4X1I1y0EhwTPh4Nu1G11Q"
    assert "secret" not in str(err.detail)


def test_empty_details_uses_safe_message_classification(monkeypatch):
    err = invoke(monkeypatch, {
        "code": 3, "status": "INVALID_ARGUMENT",
        "message": "The GAQL query has syntax errors near FROM",
    })
    assert err.detail["google_ads_error_code"] == "GOOGLE_ADS_QUERY_ERROR"
    assert err.detail["google_ads_error_category"] == "query"


def test_access_error_is_not_misdiagnosed_as_gaql(monkeypatch):
    err = invoke(monkeypatch, {
        "code": 7, "status": "PERMISSION_DENIED",
        "details": [{"errors": [{"errorCode": {"authorizationError": "CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION"}}]}],
    })
    assert err.detail["google_ads_error_code"] == "CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION"
    assert err.detail["google_ads_error_category"] == "access"
