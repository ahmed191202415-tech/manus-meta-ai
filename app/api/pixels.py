from typing import Optional
from fastapi import APIRouter, Depends

from app.config import DEFAULT_PAGE_LIMIT, DEFAULT_MAX_PAGES
from app.core.auth import resolve_access_token
from app.core.pagination import meta_get_all_pages
from app.core.meta_client import meta_call, normalize_account_id
from app.schemas.meta_requests import PixelCreateRequest

router = APIRouter(tags=["pixels"])


@router.get("/pixels")
async def list_pixels(
    account_id: str,
    fields: str = "id,name,code,last_fired_time,creation_time,owner_ad_account,event_stats,enable_automatic_matching",
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
        return meta_get_all_pages(f"{account_id}/adspixels", token, params=params, max_pages=max_pages)
    return meta_call("GET", f"{account_id}/adspixels", token, params=params)


@router.post("/pixels")
async def create_pixel(body: PixelCreateRequest, token: str = Depends(resolve_access_token)):
    account_id = normalize_account_id(body.account_id)
    payload = {"name": body.name}
    payload.update(body.extra_params)
    return meta_call("POST", f"{account_id}/adspixels", token, data=payload)
