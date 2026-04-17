from typing import Optional
from fastapi import APIRouter, Depends

from app.config import DEFAULT_PAGE_LIMIT, DEFAULT_MAX_PAGES
from app.core.auth import resolve_access_token
from app.core.pagination import meta_get_all_pages
from app.core.meta_client import meta_call, normalize_account_id

router = APIRouter(tags=["media"])


@router.get("/adimages")
async def list_adimages(
    account_id: str,
    fields: str = "hash,url,permalink_url,original_width,original_height,name,status,created_time",
    limit: int = DEFAULT_PAGE_LIMIT,
    after: Optional[str] = None,
    fetch_all: bool = False,
    max_pages: int = DEFAULT_MAX_PAGES,
    token: str = Depends(resolve_access_token),
):
    account_id = normalize_account_id(account_id)
    params = {"fields": fields, "limit": limit}
    if after:
        params["after"] = after
    if fetch_all:
        return meta_get_all_pages(f"{account_id}/adimages", token, params=params, max_pages=max_pages)
    return meta_call("GET", f"{account_id}/adimages", token, params=params)


@router.get("/advideos")
async def list_advideos(
    account_id: str,
    fields: str = "id,title,status,created_time,updated_time,source,permalink_url,thumbnails",
    limit: int = DEFAULT_PAGE_LIMIT,
    after: Optional[str] = None,
    fetch_all: bool = False,
    max_pages: int = DEFAULT_MAX_PAGES,
    token: str = Depends(resolve_access_token),
):
    account_id = normalize_account_id(account_id)
    params = {"fields": fields, "limit": limit}
    if after:
        params["after"] = after
    if fetch_all:
        return meta_get_all_pages(f"{account_id}/advideos", token, params=params, max_pages=max_pages)
    return meta_call("GET", f"{account_id}/advideos", token, params=params)
