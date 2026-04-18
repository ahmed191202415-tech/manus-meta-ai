from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
import requests

from app.config import META_APP_ID, META_APP_SECRET, META_OAUTH_REDIRECT_URI, META_OAUTH_SCOPES
from app.core.auth import _clear_meta_session, _validate_meta_access_token
from app.core.oauth_store import save_meta_connection, create_auth_code, get_meta_connection, purge_meta_connection

router = APIRouter(prefix="/auth/meta", tags=["auth"])


@router.get("/login")
async def meta_login():
    if not META_APP_ID or not META_OAUTH_REDIRECT_URI:
        raise HTTPException(status_code=500, detail="META_APP_ID or META_OAUTH_REDIRECT_URI is missing.")

    login_url = (
        "https://www.facebook.com/v23.0/dialog/oauth"
        f"?client_id={META_APP_ID}"
        f"&redirect_uri={META_OAUTH_REDIRECT_URI}"
        f"&scope={META_OAUTH_SCOPES}"
        "&response_type=code"
    )
    return RedirectResponse(url=login_url, status_code=302)


@router.get("/callback")
async def meta_callback(
    request: Request,
    code: str | None = None,
    error: str | None = None,
    error_description: str | None = None
):
    if error:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": error, "error_description": error_description}
        )

    if not code:
        raise HTTPException(status_code=400, detail="Missing OAuth code.")

    if not META_APP_ID or not META_APP_SECRET or not META_OAUTH_REDIRECT_URI:
        raise HTTPException(status_code=500, detail="META_APP_ID or META_APP_SECRET or META_OAUTH_REDIRECT_URI is missing.")

    token_url = "https://graph.facebook.com/v23.0/oauth/access_token"
    params = {
        "client_id": META_APP_ID,
        "client_secret": META_APP_SECRET,
        "redirect_uri": META_OAUTH_REDIRECT_URI,
        "code": code,
    }

    resp = requests.get(token_url, params=params, timeout=30)
    data = resp.json()

    if resp.status_code >= 400 or "access_token" not in data:
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
        return JSONResponse(status_code=400, content={"success": False, "meta_response": me_data})

    save_meta_connection(
        meta_user_id=meta_user_id,
        meta_access_token=data["access_token"],
        meta_user_name=meta_user_name,
    )

    request.session["meta_access_token"] = data["access_token"]
    request.session["meta_user_id"] = meta_user_id
    request.session["meta_user"] = me_data

    gpt_redirect_uri = request.session.get("gpt_oauth_redirect_uri")
    gpt_state = request.session.get("gpt_oauth_state")

    if gpt_redirect_uri:
        oauth_code = create_auth_code(meta_user_id=meta_user_id)
        final_url = f"{gpt_redirect_uri}?code={oauth_code}"
        if gpt_state:
            final_url += f"&state={gpt_state}"
        request.session.pop("gpt_oauth_redirect_uri", None)
        request.session.pop("gpt_oauth_state", None)
        request.session.pop("gpt_oauth_client_id", None)
        return RedirectResponse(url=final_url, status_code=302)

    return JSONResponse(
        content={
            "success": True,
            "message": "Meta login completed successfully.",
            "user": me_data,
        }
    )


@router.get("/me")
async def auth_me(request: Request):
    meta_user_id = request.session.get("meta_user_id")
    user = request.session.get("meta_user")

    if not meta_user_id:
        return {
            "logged_in": False,
            "user": None,
        }

    conn = get_meta_connection(meta_user_id)
    if not conn:
        _clear_meta_session(request)
        return {
            "logged_in": False,
            "user": None,
        }

    try:
        me_data = _validate_meta_access_token(conn["meta_access_token"])
    except HTTPException:
        purge_meta_connection(meta_user_id)
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
