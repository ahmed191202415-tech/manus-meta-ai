"""Regression tests for ChatGPT OAuth portal round trip (no live credentials)."""
from types import SimpleNamespace
import asyncio
from fastapi.responses import RedirectResponse
from app.api import tenant_portal, oauth_gpt

def test_portal_home_resumes_pending_chatgpt_oauth(monkeypatch):
    monkeypatch.setattr(tenant_portal, "ensure_allowed_tenant_by_email",
                        lambda email: {"tenant_id": "tenant-demo", "email": email})
    req = SimpleNamespace(session={
        "gpt_oauth_redirect_uri": "https://chatgpt.com/aip/callback",
        "gpt_oauth_state": "test-state",
    })
    response = asyncio.run(tenant_portal.portal_home(req, email="person@example.com"))
    assert isinstance(response, RedirectResponse)
    assert response.headers["location"] == "/oauth/continue"
    assert req.session["tenant_id"] == "tenant-demo"

def test_portal_home_normal_visit_opens_dashboard(monkeypatch):
    monkeypatch.setattr(tenant_portal, "ensure_allowed_tenant_by_email",
                        lambda email: {"tenant_id": "tenant-demo", "email": email})
    req = SimpleNamespace(session={})
    response = asyncio.run(tenant_portal.portal_home(req, email="person@example.com"))
    assert response.headers["location"] == "/portal/client"

def test_oauth_continue_reports_blocker_without_redirect_loop(monkeypatch):
    monkeypatch.setattr(oauth_gpt, "resolve_tenant_connection_state", lambda tenant: {
        "next_action": "show_reconnect",
    })
    req = SimpleNamespace(session={
        "tenant_id": "tenant-demo",
        "gpt_oauth_redirect_uri": "https://chatgpt.com/aip/callback",
        "gpt_oauth_state": "test-state",
    })
    response = asyncio.run(oauth_gpt.oauth_continue(req))
    assert response.headers["location"] == "/portal/client?oauth_error=meta_connection_not_ready"
    assert req.session["gpt_oauth_redirect_uri"] == "https://chatgpt.com/aip/callback"

def test_oauth_continue_returns_to_chatgpt_on_ready_connection(monkeypatch):
    monkeypatch.setattr(oauth_gpt, "resolve_tenant_connection_state", lambda tenant: {
        "next_action": "continue",
        "connection": {"meta_user_id": "meta-user"},
    })
    monkeypatch.setattr(oauth_gpt, "get_active_meta_connection_for_tenant", lambda tenant: {
        "meta_user_id": "meta-user", "meta_access_token": "token", "connection_mode": "manual_token",
    })
    monkeypatch.setattr(oauth_gpt, "get_tenant_meta_app", lambda tenant: None)
    monkeypatch.setattr(oauth_gpt, "_validate_meta_access_token", lambda *a, **kw: {"id": "meta-user"})
    monkeypatch.setattr(oauth_gpt, "create_auth_code", lambda **kw: "code-test")
    req = SimpleNamespace(session={
        "tenant_id": "tenant-demo",
        "gpt_oauth_redirect_uri": "https://chatgpt.com/aip/callback",
        "gpt_oauth_state": "state-test",
    })
    response = asyncio.run(oauth_gpt.oauth_continue(req))
    assert response.headers["location"] == "https://chatgpt.com/aip/callback?code=code-test&state=state-test"
    assert "gpt_oauth_redirect_uri" not in req.session
