"""Google Ads appears in the existing portal and starts independent consent.

Does not call Google or mutate any advertising account.
"""
import asyncio
from types import SimpleNamespace

from fastapi import HTTPException

from app.api import auth_google
from app.api.tenant_portal import _client_dashboard_html
from app.main import openapi_gpt_schema


def _page(connection=None):
    return _client_dashboard_html(
        tenant_id="user@example.com",
        user_email="user@example.com",
        meta_status={"meta_connection": {"connected": True}},
        google_connection=connection,
        clarity_connection=None,
        service_account_email="",
        schema_url="https://example.test/openapi-gpt.json",
        has_pending_gpt_oauth=False,
        dashboards=[],
    )


def test_google_ads_section_exists_when_ga4_only():
    page = _page({"connection_mode": "oauth", "scopes": "https://www.googleapis.com/auth/analytics.readonly"})
    assert 'Google Ads</strong>' in page
    assert 'action="/auth/google/ads/start" method="post"' in page
    assert "ربط Google Ads عبر Google" in page
    assert "Google Analytics" in page
    assert "Microsoft Clarity" in page


def test_google_ads_shows_connected_only_with_explicit_ads_scope():
    page = _page({
        "connection_mode": "oauth",
        "scopes": "https://www.googleapis.com/auth/analytics.readonly https://www.googleapis.com/auth/adwords",
    })
    assert "إعادة تفويض Google Ads" in page
    assert "اتصال Google Ads مُفعّل" in page


def test_ads_oauth_start_needs_portal_session(monkeypatch):
    request = SimpleNamespace(session={})
    try:
        asyncio.run(auth_google.google_ads_portal_start(request))
    except HTTPException as exc:
        assert exc.status_code == 401
    else:
        raise AssertionError("Expected session verification")


def test_ads_start_requests_google_ads_scope_without_schema_edit(monkeypatch):
    monkeypatch.setattr(auth_google, "get_tenant_account_by_id", lambda _: {"status": "active"})
    monkeypatch.setattr(auth_google, "is_account_expired", lambda _: False)
    captured = {}
    def fake_url(state, additional_scopes=""):
        captured["state"] = state
        captured["scopes"] = additional_scopes
        return "https://accounts.google.com/o/oauth2/v2/auth?state=opaque"
    monkeypatch.setattr(auth_google, "build_google_authorization_url", fake_url)
    request = SimpleNamespace(session={"tenant_id": "user@example.com"})
    response = asyncio.run(auth_google.google_ads_portal_start(request))
    assert response.status_code == 303
    assert response.headers["location"].startswith("https://accounts.google.com/")
    assert captured["scopes"] == "https://www.googleapis.com/auth/adwords"
    assert request.session["pending_google_tenant_id"] == "user@example.com"
    assert request.session["google_ads_connect"] is True
    assert "/tools/intent" in openapi_gpt_schema()["paths"]
