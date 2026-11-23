"""Make Google Ads 403 failures visible in the original GPT Action.

No actual Ads reads or writes. The fake responses mimic Google's errors.
"""
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import app
from app.core import google_ads_gateway as ads


def _http_error(data, status=403):
    return SimpleNamespace(
        status_code=status,
        headers={"request-id": "GoogleReq_1234"},
        json=lambda: data,
    )


def test_google_api_permission_code_is_visible_without_raw_message(monkeypatch):
    monkeypatch.setattr(ads, "_credentials", lambda tenant: {"access_token": "TOP-SECRET"})
    monkeypatch.setattr(ads.requests, "request", lambda *a, **k: _http_error({
        "error": {
            "status": "PERMISSION_DENIED",
            "message": "Sensitive upstream diagnostic or account ID",
            "details": [
                {
                    "@type": "type.googleapis.com/google.ads.googleads.v25.errors.GoogleAdsFailure",
                    "errors": [{"errorCode": {"authorizationError": "CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION"}}],
                }
            ],
        }
    }))
    from fastapi import HTTPException
    try:
        ads._api("tenant", "GET", "/customers:listAccessibleCustomers")
    except HTTPException as exc:
        detail = exc.detail
        assert exc.status_code == 403
        assert detail["google_ads_error_code"] == "CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION"
        assert detail["origin"] == "google_ads_api"
        assert detail["api_status"] == "PERMISSION_DENIED"
        assert "Explorer" in detail["next_step"]
        assert "TOP-SECRET" not in str(detail)
        assert "Sensitive upstream" not in str(detail)
    else:
        raise AssertionError("Expected provider HTTP error")


def test_read_403_becomes_clear_json_in_same_gpt_action(monkeypatch):
    monkeypatch.setattr(ads, "_required_app_identity", lambda request: {"tenant_id":"fake-tenant"})
    from fastapi import HTTPException
    def denied(tenant, method, path, body=None, **kwargs):
        raise HTTPException(403, {
            "origin": "google_ads_api",
            "http_status": 403,
            "api_status": "PERMISSION_DENIED",
            "google_ads_error_code": "CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION",
            "message": "Google Ads API rejected request.",
            "next_step": "Apply for Explorer access.",
        })
    monkeypatch.setattr(ads, "_api", denied)
    res = TestClient(app).post(
        "/tools/intent",
        json={"request": 'google_ads {"action":"list_accounts"}'},
    )
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["ok"] is False
    assert payload["status"] == "READ_FAILED"
    assert payload["http_status"] == 403
    assert payload["google_api_called"] is True
    assert payload["error"]["google_ads_error_code"] == "CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION"
    assert payload["action_diagnostics"]["route"] == "/tools/intent"
    assert payload["action_diagnostics"]["executed"] is True


def test_invalid_gpt_session_still_returns_401(monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr(ads, "_required_app_identity", lambda _: (_ for _ in ()).throw(HTTPException(401,"No GPT OAuth")))
    res=TestClient(app).post("/tools/intent",json={"request": 'google_ads {"action":"list_accounts"}'})
    assert res.status_code == 401
