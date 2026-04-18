from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import RedirectResponse

from app.core.auth import _clear_meta_session, _validate_meta_access_token
from app.core.oauth_store import create_auth_code, consume_auth_code, create_app_token
from app.core.oauth_store import get_meta_connection, purge_meta_connection
import os

router = APIRouter(prefix="/oauth", tags=["oauth"])

GPT_OAUTH_CLIENT_ID = os.getenv("GPT_OAUTH_CLIENT_ID", "gpt_client_1")
GPT_OAUTH_CLIENT_SECRET = os.getenv("GPT_OAUTH_CLIENT_SECRET", "super_secret_gpt_client_key")


@router.get("/authorize")
async def oauth_authorize(
    request: Request,
    client_id: str,
    redirect_uri: str,
    response_type: str = "code",
    state: str = "",
    scope: str = ""
):
    if client_id != GPT_OAUTH_CLIENT_ID:
        raise HTTPException(status_code=400, detail="Invalid client_id")

    if response_type != "code":
        raise HTTPException(status_code=400, detail="Unsupported response_type")

    meta_user_id = request.session.get("meta_user_id")

    if not meta_user_id:
        request.session["gpt_oauth_redirect_uri"] = redirect_uri
        request.session["gpt_oauth_state"] = state
        request.session["gpt_oauth_client_id"] = client_id
        return RedirectResponse(url="/auth/meta/login", status_code=302)

    conn = get_meta_connection(meta_user_id)
    if not conn:
        _clear_meta_session(request)
        request.session["gpt_oauth_redirect_uri"] = redirect_uri
        request.session["gpt_oauth_state"] = state
        request.session["gpt_oauth_client_id"] = client_id
        return RedirectResponse(url="/auth/meta/login", status_code=302)

    try:
        _validate_meta_access_token(conn["meta_access_token"])
    except HTTPException:
        purge_meta_connection(meta_user_id)
        _clear_meta_session(request)
        request.session["gpt_oauth_redirect_uri"] = redirect_uri
        request.session["gpt_oauth_state"] = state
        request.session["gpt_oauth_client_id"] = client_id
        return RedirectResponse(url="/auth/meta/login", status_code=302)

    code = create_auth_code(meta_user_id=meta_user_id)
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
    if client_id != GPT_OAUTH_CLIENT_ID:
        raise HTTPException(status_code=400, detail="Invalid client_id")

    if client_secret != GPT_OAUTH_CLIENT_SECRET:
        raise HTTPException(status_code=400, detail="Invalid client_secret")

    if grant_type != "authorization_code":
        raise HTTPException(status_code=400, detail="Unsupported grant_type")

    auth_data = consume_auth_code(code)
    if not auth_data:
        raise HTTPException(status_code=400, detail="Invalid or expired code")

    app_token = create_app_token(meta_user_id=auth_data["meta_user_id"])

    return {
        "access_token": app_token,
        "token_type": "bearer",
        "expires_in": 86400
    }
