from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
import os

from app.config import PORTAL_PATH, PUBLIC_BASE_URL
from app.core.connection_resolver import resolve_tenant_connection_state
from app.core.auth import _clear_meta_session, _validate_meta_access_token
from app.core.oauth_store import (
    create_app_token,
    create_auth_code,
    consume_auth_code,
    get_active_meta_connection_for_tenant,
    get_tenant_meta_app,
    purge_meta_connection,
)

router = APIRouter(prefix="/oauth", tags=["oauth"])

GPT_OAUTH_CLIENT_ID = os.getenv("GPT_OAUTH_CLIENT_ID", "gpt_client_1")
GPT_OAUTH_CLIENT_SECRET = os.getenv("GPT_OAUTH_CLIENT_SECRET", "super_secret_gpt_client_key")
DEFAULT_PUBLIC_BASE_URL = "https://manus-meta-ai-production.up.railway.app"


def _absolute_url(path: str) -> str:
    if path.startswith(("http://", "https://")):
        return path
    base = (PUBLIC_BASE_URL or DEFAULT_PUBLIC_BASE_URL).rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    return base + path


def _portal_url() -> str:
    return _absolute_url(PORTAL_PATH)


def _meta_login_url(tenant_id: str) -> str:
    return _absolute_url(f"/auth/meta/login?tenant_id={tenant_id}")


@router.get("/authorize")
async def oauth_authorize(
    request: Request,
    client_id: str,
    redirect_uri: str,
    response_type: str = "code",
    state: str = "",
    scope: str = ""
):
    del scope

    if client_id != GPT_OAUTH_CLIENT_ID:
        raise HTTPException(status_code=400, detail="Invalid client_id")

    if response_type != "code":
        raise HTTPException(status_code=400, detail="Unsupported response_type")

    tenant_id = str(request.session.get("tenant_id") or "").strip()
    if not tenant_id:
        request.session["gpt_oauth_redirect_uri"] = redirect_uri
        request.session["gpt_oauth_state"] = state
        request.session["gpt_oauth_client_id"] = client_id
        return RedirectResponse(url=_portal_url(), status_code=302)

    request.session["gpt_oauth_redirect_uri"] = redirect_uri
    request.session["gpt_oauth_state"] = state
    request.session["gpt_oauth_client_id"] = client_id

    resolution = resolve_tenant_connection_state(tenant_id)
    next_action = resolution.get("next_action")

    if next_action in {"show_setup", "show_email_gate", "show_blocked"}:
        return RedirectResponse(url=_portal_url(), status_code=302)
    if next_action in {"show_reconnect", "show_support"}:
        return RedirectResponse(url=_meta_login_url(tenant_id), status_code=302)

    meta_user_id = request.session.get("meta_user_id") or resolution.get("connection", {}).get("meta_user_id")

    conn = get_active_meta_connection_for_tenant(tenant_id)
    if not conn:
        _clear_meta_session(request)
        return RedirectResponse(url=_meta_login_url(tenant_id), status_code=302)

    try:
        meta_app = get_tenant_meta_app(tenant_id)
        _validate_meta_access_token(conn["meta_access_token"], app_secret=meta_app.get("meta_app_secret") if meta_app else None)
    except HTTPException:
        purge_meta_connection(meta_user_id, tenant_id=tenant_id)
        _clear_meta_session(request)
        request.session["tenant_id"] = tenant_id
        return RedirectResponse(url=_meta_login_url(tenant_id), status_code=302)

    code = create_auth_code(tenant_id=tenant_id, meta_user_id=meta_user_id)
    final_url = f"{redirect_uri}?code={code}"
    if state:
        final_url += f"&state={state}"
    return RedirectResponse(url=final_url, status_code=302)


@router.post("/token")
async def oauth_token(
    grant_type: str = Form(...),
    code: str = Form(...),
    client_id: str = Form(...),
    client_secret: str = Form(...),
    redirect_uri: str = Form(...)
):
    del redirect_uri

    if client_id != GPT_OAUTH_CLIENT_ID:
        raise HTTPException(status_code=400, detail="Invalid client_id")

    if client_secret != GPT_OAUTH_CLIENT_SECRET:
        raise HTTPException(status_code=400, detail="Invalid client_secret")

    if grant_type != "authorization_code":
        raise HTTPException(status_code=400, detail="Unsupported grant_type")

    auth_data = consume_auth_code(code)
    if not auth_data:
        raise HTTPException(status_code=400, detail="Invalid or expired code")

    app_token = create_app_token(tenant_id=auth_data["tenant_id"], meta_user_id=auth_data["meta_user_id"])

    return {
        "access_token": app_token,
        "token_type": "bearer",
        "expires_in": 86400
    }


@router.get("/continue")
async def oauth_continue(request: Request):
    tenant_id = str(request.session.get("tenant_id") or "").strip()
    redirect_uri = str(request.session.get("gpt_oauth_redirect_uri") or "").strip()
    state = str(request.session.get("gpt_oauth_state") or "").strip()

    if not tenant_id or not redirect_uri:
        return RedirectResponse(url=_portal_url(), status_code=302)

    resolution = resolve_tenant_connection_state(tenant_id)
    next_action = resolution.get("next_action")
    if next_action in {"show_setup", "show_email_gate", "show_blocked"}:
        return RedirectResponse(url=_portal_url(), status_code=302)
    if next_action in {"show_reconnect", "show_support"}:
        return RedirectResponse(url=_meta_login_url(tenant_id), status_code=302)

    meta_user_id = request.session.get("meta_user_id") or resolution.get("connection", {}).get("meta_user_id")
    if not meta_user_id:
        return RedirectResponse(url=_meta_login_url(tenant_id), status_code=302)

    conn = get_active_meta_connection_for_tenant(tenant_id)
    if not conn:
        _clear_meta_session(request)
        return RedirectResponse(url=_meta_login_url(tenant_id), status_code=302)

    try:
        meta_app = get_tenant_meta_app(tenant_id)
        _validate_meta_access_token(conn["meta_access_token"], app_secret=meta_app.get("meta_app_secret") if meta_app else None)
    except HTTPException:
        purge_meta_connection(meta_user_id, tenant_id=tenant_id)
        _clear_meta_session(request)
        request.session["tenant_id"] = tenant_id
        return RedirectResponse(url=_meta_login_url(tenant_id), status_code=302)

    code = create_auth_code(tenant_id=tenant_id, meta_user_id=meta_user_id)
    final_url = f"{redirect_uri}?code={code}"
    if state:
        final_url += f"&state={state}"
    request.session.pop("gpt_oauth_redirect_uri", None)
    request.session.pop("gpt_oauth_state", None)
    request.session.pop("gpt_oauth_client_id", None)
    return RedirectResponse(url=final_url, status_code=302)
