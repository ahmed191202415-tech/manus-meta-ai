from datetime import datetime, timedelta, timezone
import json
from urllib.parse import urlencode

import requests
from fastapi import HTTPException
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import service_account

from app.config import (
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_OAUTH_REDIRECT_URI,
    GOOGLE_OAUTH_SCOPES,
    GOOGLE_SERVICE_ACCOUNT_JSON,
)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


def _require_google_oauth_config():
    missing = []
    if not GOOGLE_CLIENT_ID:
        missing.append("GOOGLE_CLIENT_ID")
    if not GOOGLE_CLIENT_SECRET:
        missing.append("GOOGLE_CLIENT_SECRET")
    if not GOOGLE_OAUTH_REDIRECT_URI:
        missing.append("GOOGLE_OAUTH_REDIRECT_URI")
    if missing:
        raise HTTPException(status_code=500, detail=f"Google OAuth is not configured: {', '.join(missing)}")


def build_google_authorization_url(state: str) -> str:
    _require_google_oauth_config()
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": GOOGLE_OAUTH_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def _expires_at(expires_in: int | None) -> str | None:
    if not expires_in:
        return None
    return (datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))).isoformat()


def exchange_google_code(code: str) -> dict:
    _require_google_oauth_config()
    response = requests.post(
        GOOGLE_TOKEN_URL,
        data={
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": GOOGLE_OAUTH_REDIRECT_URI,
        },
        timeout=30,
    )
    data = response.json()
    if response.status_code >= 400 or not data.get("access_token"):
        raise HTTPException(status_code=400, detail={"message": "Google OAuth token exchange failed.", "google_response": data})
    data["expires_at"] = _expires_at(data.get("expires_in"))
    return data


def refresh_google_access_token(refresh_token: str) -> dict:
    _require_google_oauth_config()
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Google refresh token is missing. Please reconnect Google.")
    response = requests.post(
        GOOGLE_TOKEN_URL,
        data={
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    data = response.json()
    if response.status_code >= 400 or not data.get("access_token"):
        raise HTTPException(status_code=401, detail={"message": "Google token refresh failed.", "google_response": data})
    data["expires_at"] = _expires_at(data.get("expires_in"))
    return data


def fetch_google_userinfo(access_token: str) -> dict:
    response = requests.get(
        GOOGLE_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    data = response.json()
    if response.status_code >= 400:
        raise HTTPException(status_code=400, detail={"message": "Could not fetch Google user profile.", "google_response": data})
    return data


def get_google_service_account_info() -> dict:
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        raise HTTPException(status_code=503, detail="Google Service Account is not configured on the server.")
    try:
        info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="GOOGLE_SERVICE_ACCOUNT_JSON is invalid JSON.") from exc
    email = str(info.get("client_email") or "").strip()
    if not email:
        raise HTTPException(status_code=500, detail="Google Service Account JSON is missing client_email.")
    return info


def get_google_service_account_email() -> str:
    try:
        return str(get_google_service_account_info()["client_email"])
    except HTTPException:
        return ""


def get_google_service_account_token() -> dict:
    info = get_google_service_account_info()
    credentials = service_account.Credentials.from_service_account_info(
        info,
        scopes=[item for item in GOOGLE_OAUTH_SCOPES.replace(",", " ").split() if item],
    )
    credentials.refresh(GoogleAuthRequest())
    return {
        "access_token": credentials.token,
        "expires_at": credentials.expiry.isoformat() if credentials.expiry else None,
        "google_user_email": info["client_email"],
        "scopes": GOOGLE_OAUTH_SCOPES,
        "connection_mode": "service_account",
    }
