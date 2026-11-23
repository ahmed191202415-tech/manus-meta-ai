"""Exercise upstream envelopes, safe diagnostics, and read/write retry boundaries."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.core import google_ads_gateway as ads
from app.core.google_ads_errors import decode_google_ads_error


def failure(code="UNRECOGNIZED_FIELD", *, family="queryError", request_id="Google_failure_123"):
    return {"error": {
        "code": 400, "status": "INVALID_ARGUMENT",
        "message": "Bearer secret-token and refresh_token=secret-value",
        "details": [{
            "@type": "type.googleapis.com/google.ads.googleads.v25.errors.GoogleAdsFailure",
            "requestId": request_id,
            "errors": [{
                "errorCode": {family: code},
                "message": "query includes private customer text",
                "location": {"fieldPathElements": [{"fieldName": "operations", "index": 2},
                                                  {"fieldName": "updateMask"}]},
            }],
        }],
    }}


def response(payload, status=200):
    return SimpleNamespace(status_code=status, headers={}, json=lambda: payload)


@pytest.mark.parametrize("wrap", [lambda obj: obj, lambda obj: [obj]])
def test_structured_failure_survives_both_rest_envelopes(wrap):
    result = decode_google_ads_error(wrap(failure()), 400)
    assert result["google_ads_error_code"] == "UNRECOGNIZED_FIELD"
    assert result["google_ads_error_category"] == "query"
    assert result["google_ads_error_family"] == "queryError"
    assert result["google_ads_error_field"] == "operations[2].updateMask"
    assert result["google_request_id"] == "Google_failure_123"
    assert "secret" not in str(result) and "private customer" not in str(result)


def test_rpc_error_info_reason_is_preserved():
    result = decode_google_ads_error({"error": {
        "status": "PERMISSION_DENIED",
        "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo",
                     "reason": "SERVICE_DISABLED", "metadata": {"secret": "private"}}],
    }}, 403)
    assert result["google_ads_error_code"] == "SERVICE_DISABLED"
    assert "Enable Google Ads API" in result["next_step"]
    assert "private" not in str(result)


def test_later_useful_error_is_not_hidden_by_unspecified():
    payload = failure("UNSPECIFIED")
    payload["error"]["details"][0]["errors"].append(
        {"errorCode": {"authorizationError": "USER_PERMISSION_DENIED"}})
    result = decode_google_ads_error(payload, 400)
    assert result["google_ads_error_code"] == "USER_PERMISSION_DENIED"
    assert len(result["google_ads_errors"]) == 2


def test_unsafe_field_and_request_id_are_not_forwarded():
    payload = failure(request_id="secret\nforged-log")
    payload["error"]["details"][0]["errors"][0]["location"]["fieldPathElements"] = [
        {"fieldName": "Bearer secret"}, {"fieldName": "query"}]
    result = decode_google_ads_error(payload, 400, {"request-id": "bad\nid"})
    assert result["google_request_id"] is None
    assert result["google_ads_error_field"] == "query"
    assert "secret" not in str(result)


def test_provider_text_never_reaches_logs(monkeypatch, caplog):
    monkeypatch.setattr(ads, "_credentials", lambda _: {"access_token": "real-secret"})
    monkeypatch.setattr(ads.requests, "request", lambda *a, **k: response([failure()], 400))
    with pytest.raises(HTTPException):
        ads._api("tenant", "POST", "/customers/3333735582/googleAds:searchStream", {"query": "SELECT campaign.id FROM campaign"})
    assert "UNRECOGNIZED_FIELD" in caplog.text
    for secret in ("secret-token", "secret-value", "real-secret", "private customer"):
        assert secret not in caplog.text


def test_partial_stream_error_never_becomes_successful_empty_or_partial_report(monkeypatch):
    monkeypatch.setattr(ads, "_credentials", lambda _: {"access_token": "test"})
    monkeypatch.setattr(ads.requests, "request", lambda *a, **k: response(
        [{"results": [{"campaign": {"id": "1"}}]}, failure()]))
    with pytest.raises(HTTPException) as exc:
        ads._read_stream("SELECT campaign.id FROM campaign", "tenant", "3333735582")
    assert exc.value.status_code == 400
    assert exc.value.detail["google_ads_error_code"] == "UNRECOGNIZED_FIELD"


@pytest.mark.parametrize("status", [400, 401, 403])
def test_permanent_read_failures_are_not_retried(monkeypatch, status):
    calls = []
    monkeypatch.setattr(ads, "_credentials", lambda _: {"access_token": "test"})
    monkeypatch.setattr(ads.requests, "request", lambda *a, **k: calls.append(1) or response(failure(), status))
    with pytest.raises(HTTPException):
        ads._api("tenant", "POST", "/customers/3333735582/googleAds:search", {"query": "SELECT campaign.id FROM campaign"})
    assert len(calls) == 1


def test_transient_read_gets_one_bounded_retry(monkeypatch):
    replies = iter([response({"error": {"status": "UNAVAILABLE"}}, 503),
                    response({"results": [{"campaign": {"id": "1"}}]})])
    calls = []
    monkeypatch.setattr(ads, "_credentials", lambda _: {"access_token": "test"})
    monkeypatch.setattr(ads.time, "sleep", lambda _: None)
    monkeypatch.setattr(ads.requests, "request", lambda *a, **k: calls.append(1) or next(replies))
    result = ads._read("SELECT campaign.id FROM campaign", "tenant", "3333735582")
    assert len(calls) == 2
    assert result["verified_by_google_api"] is True
    assert result["count"] == 1


def test_mutation_transport_timeout_is_not_replayed(monkeypatch):
    calls = []
    monkeypatch.setattr(ads, "_credentials", lambda _: {"access_token": "test"})
    def timed_out(*args, **kwargs):
        calls.append(1)
        raise ads.requests.Timeout("sensitive upstream text")
    monkeypatch.setattr(ads.requests, "request", timed_out)
    with pytest.raises(HTTPException) as exc:
        ads._api("tenant", "POST", "/customers/3333735582/googleAds:mutate", {"validateOnly": False})
    assert len(calls) == 1
    assert exc.value.detail["outcome_unknown"] is True
    assert exc.value.detail["retryable"] is False
    assert "sensitive upstream" not in str(exc.value.detail)


def test_search_pagination_reuses_query_and_rejects_cycles(monkeypatch):
    calls = []
    def page(tenant, method, path, body, **kwargs):
        calls.append(body)
        return {"results": [], "nextPageToken": "repeated"}
    monkeypatch.setattr(ads, "_api", page)
    with pytest.raises(HTTPException) as exc:
        ads._read("SELECT campaign.id FROM campaign", "tenant", "3333735582")
    assert exc.value.status_code == 502
    assert calls == [{"query": "SELECT campaign.id FROM campaign"},
                     {"query": "SELECT campaign.id FROM campaign", "pageToken": "repeated"}]


def test_malformed_result_rows_fail_instead_of_fabricating_zeros(monkeypatch):
    monkeypatch.setattr(ads, "_api", lambda *a, **k: {"results": ["bad-row"]})
    with pytest.raises(HTTPException) as exc:
        ads._read("SELECT campaign.id FROM campaign", "tenant", "3333735582")
    assert exc.value.status_code == 502


def test_auth_storage_outage_is_not_reported_as_expired_login(monkeypatch):
    def unavailable(_):
        raise RuntimeError("database unavailable")
    monkeypatch.setattr(ads, "get_app_token_data", unavailable)
    req = Request({"type": "http", "headers": [(b"authorization", b"Bearer app_test")]})
    with pytest.raises(HTTPException) as exc:
        ads._required_app_identity(req)
    assert exc.value.status_code == 503
