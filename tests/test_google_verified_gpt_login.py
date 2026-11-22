"""Google-verified GPT login does not depend on a Meta connection."""
import asyncio
from types import SimpleNamespace
from urllib.parse import urlparse, parse_qs
import pytest
from fastapi import HTTPException
from app.api import auth_google, oauth_gpt
from app.core import oauth_store

TENANT = "tenant-A"
EMAIL = "owner@example.com"
CALLBACK = "https://chatgpt.com/aip/callback"

def req(session):
    return SimpleNamespace(session=session)

def test_unhealthy_meta_routes_to_google_identity(monkeypatch):
    monkeypatch.setattr(oauth_gpt, "resolve_tenant_connection_state",
                        lambda tenant: {"next_action": "show_reconnect"})
    response = asyncio.run(oauth_gpt.oauth_continue(req({
        "tenant_id": TENANT, "gpt_oauth_redirect_uri": CALLBACK, "gpt_oauth_state": "abc"
    })))
    assert response.headers["location"] == "/auth/google/gpt-login"

def test_verified_google_user_returns_directly_to_chatgpt(monkeypatch):
    monkeypatch.setattr(oauth_gpt, "get_tenant_account_by_id",
                        lambda tenant: {"email": EMAIL, "status": "active"})
    monkeypatch.setattr(oauth_gpt, "create_auth_code", lambda **kw: "test-code")
    session = {"tenant_id": TENANT, "gpt_oauth_redirect_uri": CALLBACK,
               "gpt_oauth_state": "test-state",
               "gpt_google_verified_email": EMAIL,
               "gpt_google_verified_tenant": TENANT}
    response = asyncio.run(oauth_gpt.oauth_continue(req(session)))
    url = urlparse(response.headers["location"])
    assert url.netloc == "chatgpt.com"
    assert parse_qs(url.query) == {"code": ["test-code"], "state": ["test-state"]}
    assert "gpt_oauth_redirect_uri" not in session

def test_identity_login_requires_active_tenant_and_pending_gpt_session(monkeypatch):
    monkeypatch.setattr(auth_google, "get_tenant_account_by_id",
                        lambda tenant: {"email": EMAIL, "status": "active"})
    monkeypatch.setattr(auth_google, "build_google_authorization_url",
                        lambda state, additional_scopes="": "https://accounts.google.com/test")
    with pytest.raises(HTTPException):
        asyncio.run(auth_google.google_gpt_identity_login(req({"tenant_id": TENANT})))
    session = {"tenant_id": TENANT, "gpt_oauth_redirect_uri": CALLBACK}
    resp = asyncio.run(auth_google.google_gpt_identity_login(req(session)))
    assert resp.headers["location"] == "https://accounts.google.com/test"
    assert session["gpt_google_identity_pending"] is True

def test_google_callback_verifies_exact_email_without_changing_saved_connections(monkeypatch):
    session = {"tenant_id": TENANT, "pending_google_tenant_id": TENANT,
               "google_oauth_state": "nonce",
               "gpt_google_identity_pending": True,
               "gpt_oauth_redirect_uri": CALLBACK}
    monkeypatch.setattr(auth_google, "exchange_google_code",
                        lambda code: {"access_token": "test"})
    monkeypatch.setattr(auth_google, "fetch_google_userinfo",
                        lambda token: {"email": EMAIL, "verified_email": True})
    monkeypatch.setattr(auth_google, "get_tenant_account_by_id",
                        lambda tenant: {"email": EMAIL, "status": "active"})
    monkeypatch.setattr(auth_google, "save_google_connection",
                        lambda *a, **kw: pytest.fail("Must never alter saved provider connection"))
    response = asyncio.run(auth_google.google_callback(req(session), code="code", state="nonce"))
    assert response.headers["location"] == "/oauth/continue"
    assert session["gpt_google_verified_email"] == EMAIL

@pytest.mark.parametrize("user_email,verified", [
    ("other@example.com", True),
    (EMAIL, False),
])
def test_google_identity_rejects_wrong_or_unverified_email(monkeypatch, user_email, verified):
    session = {"tenant_id": TENANT, "pending_google_tenant_id": TENANT,
               "google_oauth_state": "nonce", "gpt_google_identity_pending": True}
    monkeypatch.setattr(auth_google, "exchange_google_code",
                        lambda code: {"access_token": "test"})
    monkeypatch.setattr(auth_google, "fetch_google_userinfo",
                        lambda token: {"email": user_email, "verified_email": verified})
    monkeypatch.setattr(auth_google, "get_tenant_account_by_id",
                        lambda tenant: {"email": EMAIL, "status": "active"})
    with pytest.raises(HTTPException) as exc:
        asyncio.run(auth_google.google_callback(req(session), code="code", state="nonce"))
    assert exc.value.status_code == 403
    assert "gpt_google_verified_tenant" not in session

def test_tenant_only_gpt_token_is_scoped_and_has_no_meta_credentials(monkeypatch):
    from datetime import datetime, timedelta, timezone
    monkeypatch.setattr(oauth_store, "_get_single", lambda table, params=None: {
        "tenant_id": TENANT,
        "meta_user_id": "__gpt_google_identity__",
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    })
    monkeypatch.setattr(oauth_store, "get_tenant_account_by_id",
                        lambda tenant: {"email": EMAIL, "status": "active"})
    monkeypatch.setattr(oauth_store, "get_meta_connection",
                        lambda *a, **kw: pytest.fail("Must not resolve Meta token"))
    result = oauth_store.get_app_token_data("app_testing")
    assert result["tenant_id"] == TENANT
    assert result["meta_access_token"] is None
