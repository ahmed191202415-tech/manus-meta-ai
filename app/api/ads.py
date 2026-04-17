from typing import Optional
from fastapi import APIRouter, Depends

from app.config import DEFAULT_PAGE_LIMIT, DEFAULT_MAX_PAGES
from app.core.auth import resolve_access_token
from app.core.pagination import meta_get_all_pages
from app.core.meta_client import meta_call, normalize_account_id
from app.schemas.meta_requests import AdCreateRequest

router = APIRouter(tags=["ads"])


@router.get("/ads")
async def list_ads(
    account_id: str,
    fields: str = "id,name,adset_id,campaign_id,status,effective_status,creative,tracking_specs,created_time,updated_time",
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
        return meta_get_all_pages(f"{account_id}/ads", token, params=params, max_pages=max_pages)

    return meta_call("GET", f"{account_id}/ads", token, params=params)


@router.post("/ads")
async def create_ad(body: AdCreateRequest, token: str = Depends(resolve_access_token)):
    account_id = normalize_account_id(body.account_id)

    payload = {
        "name": body.name,
        "adset_id": body.adset_id,
        "creative": body.creative,
        "status": body.status,
    }

    if body.tracking_specs is not None:
        payload["tracking_specs"] = body.tracking_specs

    payload.update(body.extra_params)

    return meta_call("POST", f"{account_id}/ads", token, data=payload)
