from typing import Optional
from fastapi import Header, Query, HTTPException


async def resolve_access_token(
    authorization: Optional[str] = Header(None),
    access_token: Optional[str] = Query(None),
) -> str:
    if access_token:
        return access_token
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    raise HTTPException(
        status_code=401,
        detail="Provide access token in Authorization: Bearer <token> or access_token query param."
    )