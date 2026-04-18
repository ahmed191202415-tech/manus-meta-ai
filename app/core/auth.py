from typing import Optional

import requests
from fastapi import Header, Query, HTTPException, Request

from app.core.oauth_store import get_app_token_data, SUPABASE_URL, _headers


async def resolve_access_token(
    request: Request,
    authorization: Optional[str] = Header(None),
    access_token: Optional[str] = Query(None),
) -> str:
    # 1) لو التوكن جاي مباشرة في query
    if access_token:
        return access_token

    # 2) لو جاي في Authorization header
    if authorization and authorization.lower().startswith("bearer "):
        bearer = authorization.split(" ", 1)[1].strip()

        # لو ده app token داخلي من GPT OAuth
        app_token_data = get_app_token_data(bearer)
        if app_token_data and app_token_data.get("meta_access_token"):
            return app_token_data["meta_access_token"]

        # لو المستخدم باعت Meta token مباشر
        return bearer

    # 3) لو موجود في session
    session_token = request.session.get("meta_access_token")
    if session_token:
        return session_token

    # 4) fallback: هات آخر Meta token محفوظ من Supabase
    if SUPABASE_URL:
        url = f"{SUPABASE_URL}/rest/v1/meta_connections"
        params = {
            "select": "meta_access_token",
            "order": "updated_at.desc",
            "limit": "1",
        }

        resp = requests.get(url, headers=_headers(), params=params, timeout=30)
        resp.raise_for_status()

        data = resp.json()
        if data and data[0].get("meta_access_token"):
            return data[0]["meta_access_token"]

    raise HTTPException(
        status_code=401,
        detail="No access token found. Login first via /auth/meta/login or pass token manually."
    )