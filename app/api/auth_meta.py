from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from itsdangerous import BadSignature, URLSafeSerializer
import requests
from urllib.parse import urlencode

from app.config import META_OAUTH_REDIRECT_URI, META_OAUTH_SCOPES, PORTAL_PATH, SESSION_SECRET
from app.core.connection_resolver import resolve_tenant_connection_state
from app.core.auth import _clear_meta_session, _validate_meta_access_token
from app.core.oauth_store import (
    create_auth_code,
    get_active_meta_connection_for_tenant,
    get_tenant_meta_app_required,
    purge_meta_connection,
    purge_meta_connections_for_tenant,
    save_meta_connection,
)

router = APIRouter(prefix="/auth/meta", tags=["auth"])


def _meta_state_serializer() -> URLSafeSerializer:
    return URLSafeSerializer(SESSION_SECRET, salt="meta-oauth-state")


def _encode_meta_state(request: Request, tenant_id: str) -> str:
    return _meta_state_serializer().dumps({
        "tenant_id": tenant_id,
        "gpt_redirect_uri": request.session.get("gpt_oauth_redirect_uri"),
        "gpt_state": request.session.get("gpt_oauth_state"),
    })


def _decode_meta_state(state: str | None) -> dict:
    if not state:
        return {}
    try:
        payload = _meta_state_serializer().loads(state)
    except BadSignature:
        return {}
    return payload if isinstance(payload, dict) else {}


def _portal_with_meta_error(request: Request, reason: str, detail: object) -> RedirectResponse:
    request.session["meta_oauth_error"] = {
        "reason": str(reason)[:120],
        "detail": str(detail)[:800],
    }
    return RedirectResponse(url=f"{PORTAL_PATH}?meta_error={reason}", status_code=302)


def _is_desktop_app_error(payload: dict) -> bool:
    error = payload.get("error", payload) if isinstance(payload, dict) else {}
    message = str(error.get("message") if isinstance(error, dict) else "").lower()
    return "configured as a desktop app" in message


def _oauth_redirect_url(redirect_uri: str, code: str, state: str | None = None) -> str:
    separator = "&" if "?" in redirect_uri else "?"
    params = {"code": code}
    if state:
        params["state"] = state
    return f"{redirect_uri}{separator}{urlencode(params)}"


def _meta_login_url(meta_app: dict, state: str, response_type: str = "code") -> str:
    params = {
        "client_id": meta_app["meta_app_id"],
        "redirect_uri": META_OAUTH_REDIRECT_URI,
        "response_type": response_type,
        "state": state,
        "scope": meta_app.get("meta_oauth_scopes") or META_OAUTH_SCOPES,
    }
    return "https://www.facebook.com/v23.0/dialog/oauth?" + urlencode(params)


def _token_bridge_html() -> str:
    return """<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Connecting Meta</title>
  <style>body{font-family:Tahoma,Arial,sans-serif;padding:28px;line-height:1.7}</style>
</head>
<body>
  <p>جاري حفظ ربط Meta...</p>
  <script>
    async function finish() {
      const params = new URLSearchParams(window.location.hash.replace(/^#/, ""));
      const accessToken = params.get("access_token");
      const state = params.get("state");
      const error = params.get("error") || params.get("error_description");
      if (error) {
        document.body.innerHTML = "<pre>" + error + "</pre>";
        return;
      }
      if (!accessToken) {
        document.body.innerHTML = "<pre>Meta did not return an access token.</pre>";
        return;
      }
      const response = await fetch("/auth/meta/token_callback", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        credentials: "include",
        body: JSON.stringify({access_token: accessToken, state})
      });
      const text = await response.text();
      let data = {};
      try { data = text ? JSON.parse(text) : {}; } catch { data = {detail: text}; }
      if (!response.ok) {
        document.body.innerHTML = "<pre>" + JSON.stringify(data, null, 2) + "</pre>";
        return;
      }
      window.location.href = data.redirect_url || "/portal?connected=1";
    }
    finish();
  </script>
</body>
</html>"""


async def _save_meta_access_token(request: Request, access_token: str, state_data: dict) -> dict:
    tenant_id = str(
        request.session.get("pending_meta_tenant_id")
        or request.session.get("tenant_id")
        or state_data.get("tenant_id")
        or ""
    ).strip()
    if not tenant_id:
        raise HTTPException(status_code=400, detail="No tenant was selected for Meta authentication.")

    me_resp = requests.get(
        "https://graph.facebook.com/me",
        params={"fields": "id,name", "access_token": access_token},
        timeout=30,
    )
    me_data = me_resp.json()
    meta_user_id = me_data.get("id")
    meta_user_name = me_data.get("name")
    if not meta_user_id:
        raise HTTPException(status_code=400, detail={"message": "Could not fetch Meta user profile.", "meta_response": me_data})

    save_meta_connection(
        tenant_id=tenant_id,
        meta_user_id=meta_user_id,
        meta_access_token=access_token,
        meta_user_name=meta_user_name,
        granted_scopes=None,
    )

    request.session["meta_access_token"] = access_token
    request.session["meta_user_id"] = meta_user_id
    request.session["meta_user"] = me_data
    request.session["tenant_id"] = tenant_id
    request.session.pop("pending_meta_tenant_id", None)
    return {"tenant_id": tenant_id, "meta_user_id": meta_user_id, "me": me_data}


def _finish_meta_redirect(request: Request, tenant_id: str, meta_user_id: str, state_data: dict) -> str:
    gpt_redirect_uri = request.session.get("gpt_oauth_redirect_uri") or state_data.get("gpt_redirect_uri")
    gpt_state = request.session.get("gpt_oauth_state") or state_data.get("gpt_state")
    if gpt_redirect_uri:
        oauth_code = create_auth_code(tenant_id=tenant_id, meta_user_id=meta_user_id)
        request.session.pop("gpt_oauth_redirect_uri", None)
        request.session.pop("gpt_oauth_state", None)
        request.session.pop("gpt_oauth_client_id", None)
        return _oauth_redirect_url(gpt_redirect_uri, oauth_code, gpt_state)
    return f"{PORTAL_PATH}?connected=1"


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

    request.session["tenant_id"] = tenant_id
    request.session["pending_meta_tenant_id"] = tenant_id
    login_url = _meta_login_url(meta_app, _encode_meta_state(request, tenant_id), response_type="code")
    return RedirectResponse(url=login_url, status_code=302)


@router.get("/callback")
async def meta_callback(
    request: Request,
    code: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    state: str | None = None,
):
    state_data = _decode_meta_state(state)
    if not code and not error:
        return HTMLResponse(_token_bridge_html())

    if error:
        if request.session.get("gpt_oauth_redirect_uri") or state_data.get("gpt_redirect_uri") or request.session.get("tenant_id"):
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
        or state_data.get("tenant_id")
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
        if _is_desktop_app_error(data):
            fallback_url = _meta_login_url(meta_app, state or _encode_meta_state(request, tenant_id), response_type="token")
            return RedirectResponse(url=fallback_url, status_code=302)
        if request.session.get("gpt_oauth_redirect_uri") or state_data.get("gpt_redirect_uri") or request.session.get("tenant_id"):
            return _portal_with_meta_error(request, "token_exchange_failed", data)
        return JSONResponse(status_code=400, content={"success": False, "meta_response": data})

    try:
        saved = await _save_meta_access_token(request, data["access_token"], state_data)
    except Exception as exc:
        return _portal_with_meta_error(request, "connection_save_failed", exc)

    return RedirectResponse(url=_finish_meta_redirect(request, saved["tenant_id"], saved["meta_user_id"], state_data), status_code=302)


@router.post("/token_callback")
async def meta_token_callback(request: Request):
    body = await request.json()
    access_token = str((body or {}).get("access_token") or "").strip()
    state = str((body or {}).get("state") or "").strip()
    if not access_token:
        raise HTTPException(status_code=400, detail="access_token is required.")
    state_data = _decode_meta_state(state)
    saved = await _save_meta_access_token(request, access_token, state_data)
    return {
        "success": True,
        "tenant_id": saved["tenant_id"],
        "redirect_url": _finish_meta_redirect(request, saved["tenant_id"], saved["meta_user_id"], state_data),
    }


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


@router.post("/disconnect")
async def auth_disconnect(request: Request, tenant_id: str | None = None):
    resolved_tenant_id = str(tenant_id or request.session.get("tenant_id") or "").strip()
    if not resolved_tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id is required.")
    purge_meta_connections_for_tenant(resolved_tenant_id)
    _clear_meta_session(request)
    request.session["tenant_id"] = resolved_tenant_id
    return {
        "success": True,
        "tenant_id": resolved_tenant_id,
        "message": "Meta connection was removed. You can connect Meta again now.",
    }


@router.get("/disconnect")
async def auth_disconnect_page(request: Request, tenant_id: str | None = None):
    await auth_disconnect(request, tenant_id=tenant_id)
    return RedirectResponse(url=f"{PORTAL_PATH}?meta_disconnected=1", status_code=302)
