from typing import Optional
from fastapi import Header, Query, HTTPException, Request


async def resolve_access_token(
    request: Request,
    authorization: Optional[str] = Header(None),
    access_token: Optional[str] = Query(None),
) -> str:
    if access_token:
        return access_token

    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()

    session_token = request.session.get("meta_access_token")
    if session_token:
        return session_token

    raise HTTPException(
        status_code=401,
        detail="No access token found. Login first via /auth/meta/login or pass token manually."
    )
