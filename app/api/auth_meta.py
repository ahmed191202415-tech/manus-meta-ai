from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
import requests

from app.config import META_APP_ID, META_APP_SECRET, META_OAUTH_REDIRECT_URI, META_OAUTH_SCOPES

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
async def meta_callback(request: Request, code: str | None = None, error: str | None = None, error_description: str | None = None):
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

    request.session["meta_access_token"] = data["access_token"]
    request.session["meta_token_type"] = data.get("token_type")
    request.session["meta_expires_in"] = data.get("expires_in")

    me_resp = requests.get(
        "https://graph.facebook.com/me",
        params={"fields": "id,name", "access_token": data["access_token"]},
        timeout=30,
    )
    me_data = me_resp.json()
    request.session["meta_user"] = me_data

    return JSONResponse(
        content={
            "success": True,
            "message": "Meta login completed successfully.",
            "user": me_data,
        }
    )


@router.get("/me")
async def auth_me(request: Request):
    token = request.session.get("meta_access_token")
    user = request.session.get("meta_user")

    return {
        "logged_in": bool(token),
        "user": user,
    }


@router.post("/logout")
async def auth_logout(request: Request):
    request.session.clear()
    return {"success": True, "message": "Logged out successfully."}
