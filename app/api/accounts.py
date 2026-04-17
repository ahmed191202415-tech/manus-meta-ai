from typing import Optional
from fastapi import APIRouter, Depends

from app.config import DEFAULT_PAGE_LIMIT
from app.core.auth import resolve_access_token
from app.core.pagination import meta_get_all_pages
from app.core.meta_client import meta_call

router = APIRouter(tags=["accounts"])


@router.get("/accounts")
async def list_accounts(
    business_id: Optional[str] = None,
    user_id: str = "me",
    fields: str = "id,name,account_id,account_status,currency,timezone_name,business",
    limit: int = DEFAULT_PAGE_LIMIT,
    fetch_all: bool = False,
    max_pages: int = 10,
    token: str = Depends(resolve_access_token),
):
    path = f"{business_id}/owned_ad_accounts" if business_id else f"{user_id}/adaccounts"
    params = {"fields": fields, "limit": limit}

    if fetch_all:
        return meta_get_all_pages(path, token, params=params, max_pages=max_pages)

    return meta_call("GET", path, token, params=params)
