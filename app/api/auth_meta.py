from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
import requests

from app.config import META_OAUTH_REDIRECT_URI, META_OAUTH_SCOPES, PORTAL_PATH
from app.core.connection_resolver import resolve_tenant_connection_state
from app.core.auth import _clear_meta_session, _validate_meta_access_token
from app.core.oauth_store import (
    create_auth_code,
    get_active_meta_connection_for_tenant,
    get_tenant_meta_app_required,
    purge_meta_connection,
    save_meta_connection,
)

router = APIRouter(prefix="/auth/meta", tags=["auth"])


@router.get("/login")
async def meta_login(request: Request, tenant_id: str | None = None):
    tenant_id = str(tenant_id or request.session.get("tenant_id") or "").strip()
    if not tenant_id:
        return RedirectResponse(url=PORTAL_PATH, status_code=302)
    if not META_OAUTH_REDIRECT_URI:
        raise HTTPException(status_code=500, detail="META_OAUTH_REDIRECT_URI is missing.")

    resolution = resolve_tenant_connection_state(tenant_id)
    if resolution.get("next_action") in {"show_setup", "show_email_gate", "show_blocked"}:
        return RedirectResponse(url=PORTAL_PATH, status_code=302)

    try:
        meta_app = get_tenant_meta_app_required(tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    scopes = meta_app.get("meta_oauth_scopes") or META_OAUTH_SCOPES
    login_url = (
        "https://www.facebook.com/v23.0/dialog/oauth"
        f"?client_id={meta_app['meta_app_id']}"
        f"&redirect_uri={META_OAUTH_REDIRECT_URI}"
        f"&scope={scopes}"
        "&response_type=code"
    )
    request.session["tenant_id"] = tenant_id
    request.session["pending_meta_tenant_id"] = tenant_id
    return RedirectResponse(url=login_url, status_code=302)


@router.get("/callback")
async def meta_callback(
    request: Request,
    code: str | None = None,
    error: str | None = None,
    error_description: str | None = None
):
    if error:
        if request.session.get("gpt_oauth_redirect_uri") or request.session.get("tenant_id"):
            return RedirectResponse(url=PORTAL_PATH, status_code=302)
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": error, "error_description": error_description}
        )

    if not code:
        raise HTTPException(status_code=400, detail="Missing OAuth code.")

    tenant_id = str(
        request.session.get("pending_meta_tenant_id")
        or request.session.get("tenant_id")
        or ""
    ).strip()
    if not tenant_id:
        raise HTTPException(status_code=400, detail="No tenant was selected for Meta authentication.")
    if not META_OAUTH_REDIRECT_URI:
        raise HTTPException(status_code=500, detail="META_OAUTH_REDIRECT_URI is missing.")

    try:
        meta_app = get_tenant_meta_app_required(tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    token_url = "https://graph.facebook.com/v23.0/oauth/access_token"
    params = {
        "client_id": meta_app["meta_app_id"],
        "client_secret": meta_app["meta_app_secret"],
        "redirect_uri": META_OAUTH_REDIRECT_URI,
        "code": code,
    }

    resp = requests.get(token_url, params=params, timeout=30)
    data = resp.json()

    if resp.status_code >= 400 or "access_token" not in data:
        if request.session.get("gpt_oauth_redirect_uri") or request.session.get("tenant_id"):
            return RedirectResponse(url=PORTAL_PATH, status_code=302)
        return JSONResponse(status_code=400, content={"success": False, "meta_response": data})

    me_resp = requests.get(
        "https://graph.facebook.com/me",
        params={"fields": "id,name", "access_token": data["access_token"]},
        timeout=30,
    )
    me_data = me_resp.json()

    meta_user_id = me_data.get("id")
    meta_user_name = me_data.get("name")

    if not meta_user_id:
        if request.session.get("gpt_oauth_redirect_uri") or request.session.get("tenant_id"):
            return RedirectResponse(url=PORTAL_PATH, status_code=302)
        return JSONResponse(status_code=400, content={"success": False, "meta_response": me_data})

    granted_scopes = data.get("granted_scopes")
    save_meta_connection(
        tenant_id=tenant_id,
        meta_user_id=meta_user_id,
        meta_access_token=data["access_token"],
        meta_user_name=meta_user_name,
        granted_scopes=",".join(granted_scopes) if isinstance(granted_scopes, list) else None,
    )

    request.session["meta_access_token"] = data["access_token"]
    request.session["meta_user_id"] = meta_user_id
    request.session["meta_user"] = me_data
    request.session["tenant_id"] = tenant_id
    request.session.pop("pending_meta_tenant_id", None)

    gpt_redirect_uri = request.session.get("gpt_oauth_redirect_uri")
    gpt_state = request.session.get("gpt_oauth_state")

    if gpt_redirect_uri:
        oauth_code = create_auth_code(tenant_id=tenant_id, meta_user_id=meta_user_id)
        final_url = f"{gpt_redirect_uri}?code={oauth_code}"
        if gpt_state:
            final_url += f"&state={gpt_state}"
        request.session.pop("gpt_oauth_redirect_uri", None)
        request.session.pop("gpt_oauth_state", None)
        request.session.pop("gpt_oauth_client_id", None)
        return RedirectResponse(url=final_url, status_code=302)

    return RedirectResponse(url=f"{PORTAL_PATH}?connected=1", status_code=302)


@router.get("/me")
async def auth_me(request: Request):
    tenant_id = request.session.get("tenant_id")
    meta_user_id = request.session.get("meta_user_id")
    user = request.session.get("meta_user")

    if not meta_user_id or not tenant_id:
        return {
            "logged_in": False,
            "user": None,
        }

    conn = get_active_meta_connection_for_tenant(tenant_id)
    if not conn:
        _clear_meta_session(request)
        return {
            "logged_in": False,
            "user": None,
        }

    try:
        meta_app = get_tenant_meta_app_required(tenant_id)
        me_data = _validate_meta_access_token(conn["meta_access_token"], app_secret=meta_app.get("meta_app_secret"))
    except (HTTPException, ValueError):
        purge_meta_connection(meta_user_id, tenant_id=tenant_id)
        _clear_meta_session(request)
        return {
            "logged_in": False,
            "user": None,
        }

    request.session["meta_access_token"] = conn["meta_access_token"]
    request.session["meta_user_id"] = str(me_data.get("id") or meta_user_id)
    request.session["meta_user"] = {
        "id": me_data.get("id"),
        "name": me_data.get("name"),
    }

    return {
        "logged_in": True,
        "user": request.session.get("meta_user") or user,
    }


@router.post("/logout")
async def auth_logout(request: Request):
    _clear_meta_session(request)
    return {"success": True, "message": "Logged out successfully."}
