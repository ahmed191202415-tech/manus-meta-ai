import secrets

import requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.config import PORTAL_PATH
from app.core.google_oauth import (
    build_google_authorization_url,
    exchange_google_code,
    fetch_google_userinfo,
    get_google_service_account_email,
    get_google_service_account_token,
)
from app.core.oauth_store import get_active_google_connection_for_tenant, purge_google_connection, save_google_connection
from app.schemas.tenant_requests import TenantGoogleServiceAccountRequest

router = APIRouter(prefix="/auth/google", tags=["google-auth"])


def _tenant_id_from_request(request: Request, tenant_id: str | None = None) -> str:
    resolved = str(tenant_id or request.session.get("tenant_id") or "").strip()
    if not resolved:
        raise HTTPException(status_code=401, detail="Tenant is required before connecting Google.")
    return resolved


@router.get("/login")
async def google_login(request: Request, tenant_id: str | None = None):
    resolved_tenant_id = _tenant_id_from_request(request, tenant_id)
    state = secrets.token_urlsafe(24)
    request.session["tenant_id"] = resolved_tenant_id
    request.session["google_oauth_state"] = state
    request.session["pending_google_tenant_id"] = resolved_tenant_id
    return RedirectResponse(url=build_google_authorization_url(state), status_code=302)


@router.get("/callback")
async def google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
):
    if error:
        raise HTTPException(status_code=400, detail={"error": error, "error_description": error_description})

    expected_state = str(request.session.get("google_oauth_state") or "")
    if not state or state != expected_state:
        raise HTTPException(status_code=400, detail="Invalid Google OAuth state.")
    if not code:
        raise HTTPException(status_code=400, detail="Missing Google OAuth code.")

    tenant_id = str(request.session.get("pending_google_tenant_id") or request.session.get("tenant_id") or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=400, detail="No tenant was selected for Google authentication.")

    token_data = exchange_google_code(code)
    try:
        userinfo = fetch_google_userinfo(token_data["access_token"])
    except HTTPException:
        userinfo = {"email": tenant_id}
    previous = get_active_google_connection_for_tenant(tenant_id) or {}
    purge_google_connection(tenant_id)
    connection = save_google_connection(
        tenant_id,
        {
            "google_user_email": userinfo.get("email"),
            "access_token": token_data.get("access_token"),
            "refresh_token": token_data.get("refresh_token"),
            "expires_at": token_data.get("expires_at"),
            "scopes": token_data.get("scope"),
            "connection_mode": "oauth",
            "selected_ga4_property_id": previous.get("selected_ga4_property_id"),
            "selected_ga4_property_name": previous.get("selected_ga4_property_name"),
        },
    )

    request.session["tenant_id"] = tenant_id
    request.session["google_user_email"] = connection.get("google_user_email")
    request.session.pop("google_oauth_state", None)
    request.session.pop("pending_google_tenant_id", None)
    return RedirectResponse(url=f"{PORTAL_PATH}?google_connected=1", status_code=302)


@router.post("/disconnect")
async def google_disconnect(request: Request, tenant_id: str | None = None):
    resolved_tenant_id = _tenant_id_from_request(request, tenant_id)
    purge_google_connection(resolved_tenant_id)
    request.session.pop("google_user_email", None)
    return {"success": True, "tenant_id": resolved_tenant_id}


@router.get("/service_account")
async def google_service_account_info():
    email = get_google_service_account_email()
    return {
        "configured": bool(email),
        "service_account_email": email or None,
        "instructions": "Grant this email Viewer access to the GA4 property, then connect the property ID.",
    }


@router.post("/connect_service_account")
async def google_connect_service_account(body: TenantGoogleServiceAccountRequest, request: Request):
    tenant_id = _tenant_id_from_request(request)
    credentials = get_google_service_account_token()
    response = requests.post(
        f"https://analyticsdata.googleapis.com/v1beta/properties/{body.property_id}:runReport",
        headers={"Authorization": f"Bearer {credentials['access_token']}", "Content-Type": "application/json"},
        json={"metrics": [{"name": "activeUsers"}], "dateRanges": [{"startDate": "7daysAgo", "endDate": "today"}], "limit": "1"},
        timeout=30,
    )
    if response.status_code >= 400:
        raise HTTPException(
            status_code=403,
            detail="Service Account cannot read this GA4 property. Add the shown service account email as Viewer, then try again.",
        )
    purge_google_connection(tenant_id)
    connection = save_google_connection(
        tenant_id,
        {
            **credentials,
            "selected_ga4_property_id": body.property_id,
            "selected_ga4_property_name": body.property_name,
        },
    )
    return {
        "success": True,
        "tenant_id": tenant_id,
        "connection_mode": "service_account",
        "google_user_email": connection.get("google_user_email"),
        "selected_ga4_property_id": body.property_id,
        "selected_ga4_property_name": body.property_name,
    }
