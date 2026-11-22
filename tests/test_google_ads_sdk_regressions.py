"""Real protobuf error fixtures for the tenant-scoped SDK; no network calls."""
from types import SimpleNamespace

import grpc
import pytest
from fastapi import HTTPException
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException
from google.ads.googleads.v26.errors.types.errors import GoogleAdsError, GoogleAdsFailure
from google.ads.googleads.v26.errors.types.query_error import QueryErrorEnum
from google.ads.googleads.v26.errors.types.authorization_error import AuthorizationErrorEnum
from google.ads.googleads.v26.services.types.google_ads_service import GoogleAdsRow

from app.core import google_ads_sdk as sdk


def failure(kind="query", request_id="request_test_123"):
    error = GoogleAdsError(message="access_token=secret never expose")
    if kind == "query":
        error.error_code.query_error = QueryErrorEnum.QueryError.UNRECOGNIZED_FIELD
        status = grpc.StatusCode.INVALID_ARGUMENT
    else:
        error.error_code.authorization_error = AuthorizationErrorEnum.AuthorizationError.USER_PERMISSION_DENIED
        status = grpc.StatusCode.PERMISSION_DENIED
    error.location.field_path_elements.append({"field_name": "query"})
    return GoogleAdsException(
        error=SimpleNamespace(code=lambda: status), call=None,
        failure=GoogleAdsFailure(errors=[error]), request_id=request_id,
    )


def test_real_protobuf_integer_error_is_resolved_to_symbol():
    err = failure()
    assert isinstance(err.failure.errors[0].error_code._pb.ListFields()[0][1], int)
    status, detail = sdk._sdk_failure(err)
    assert status == 400
    assert detail["google_ads_error_code"] == "UNRECOGNIZED_FIELD"
    assert detail["google_ads_error_category"] == "query"
    assert detail["google_ads_error_field"] == "query"
    assert detail["google_request_id"] == "request_test_123"
    assert "secret" not in str(detail)


def test_access_error_and_untrusted_request_id_are_distinguished():
    status, detail = sdk._sdk_failure(failure("access", "secret\naccess_token=x"))
    assert status == 403
    assert detail["google_ads_error_code"] == "USER_PERMISSION_DENIED"
    assert detail["google_ads_error_category"] == "access"
    assert detail["google_request_id"] is None


def test_failed_iteration_withholds_partial_sdk_rows(monkeypatch):
    def iterator():
        yield GoogleAdsRow(campaign={"id": 123, "name": "test"})
        raise failure()
    client = SimpleNamespace(get_service=lambda *a, **k: SimpleNamespace(search=lambda **kw: iterator()))
    monkeypatch.setattr(sdk, "official_client_for_tenant", lambda *a, **k: client)
    with pytest.raises(HTTPException) as caught:
        sdk.sdk_search("tenant-a", "1234567890", "SELECT campaign.id FROM campaign")
    assert caught.value.status_code == 400
    assert caught.value.detail["google_ads_error_code"] == "UNRECOGNIZED_FIELD"
    assert "rows" not in caught.value.detail


def test_sdk_reports_provenance_and_truncation(monkeypatch):
    def get_service(name, version):
        assert name == "GoogleAdsService" and version == "v26"
        return SimpleNamespace(search=lambda **kw: iter([
            GoogleAdsRow(campaign={"id": 123}), GoogleAdsRow(campaign={"id": 456}),
        ]))
    monkeypatch.setattr(sdk, "official_client_for_tenant", lambda *a, **k: SimpleNamespace(get_service=get_service))
    result = sdk.sdk_search("tenant-a", "123-456-7890", "SELECT campaign.id FROM campaign", limit=1)
    assert result["rows"] == [{"campaign": {"id": "123"}}]
    assert result["truncated"] is True
    assert result["verified_by_google_api"] is True
    assert result["query_method"] == "GoogleAdsService.Search"


def test_sdk_manager_default_matches_rest_without_global_refresh_token(monkeypatch):
    monkeypatch.setenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID", "999-888-7777")
    monkeypatch.delenv("GOOGLE_ADS_DEVELOPER_TOKEN", raising=False)
    monkeypatch.setattr(sdk, "GOOGLE_CLIENT_ID", "client-test")
    monkeypatch.setattr(sdk, "GOOGLE_CLIENT_SECRET", "client-secret-test")
    seen = []
    def saved(tenant):
        assert tenant == "tenant-a"
        return {"connection_mode": "oauth", "scopes": "https://www.googleapis.com/auth/adwords", "refresh_token": "tenant-refresh"}
    monkeypatch.setattr(sdk, "get_active_google_connection_for_tenant", saved)
    monkeypatch.setattr(GoogleAdsClient, "load_from_dict", lambda config: seen.append(config) or object())
    sdk.official_client_for_tenant("tenant-a")
    sdk.official_client_for_tenant("tenant-a", "111-222-3333")
    assert [config["login_customer_id"] for config in seen] == ["9998887777", "1112223333"]
    assert all(config["refresh_token"] == "tenant-refresh" for config in seen)
    assert all("developer_token" not in config for config in seen)


@pytest.mark.parametrize("limit", [True, 0, -1, "invalid", 1.5, None])
def test_invalid_sdk_limit_fails_before_credential_lookup(monkeypatch, limit):
    monkeypatch.setattr(sdk, "official_client_for_tenant", lambda *a, **k: pytest.fail("No credential lookup expected"))
    with pytest.raises(HTTPException) as caught:
        sdk.sdk_search("tenant-a", "1234567890", "SELECT campaign.id FROM campaign", limit=limit)
    assert caught.value.status_code == 422
