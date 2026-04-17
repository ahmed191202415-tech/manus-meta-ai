from typing import Optional
from fastapi import APIRouter, Depends

from app.config import DEFAULT_PAGE_LIMIT, DEFAULT_MAX_PAGES
from app.core.auth import resolve_access_token
from app.core.pagination import meta_get_all_pages
from app.core.meta_client import meta_call, normalize_account_id
from app.schemas.meta_requests import CampaignCreateRequest

router = APIRouter(tags=["campaigns"])


@router.get("/campaigns")
async def list_campaigns(
    account_id: str,
    fields: str = "id,name,status,effective_status,objective,buying_type,daily_budget,lifetime_budget,start_time,stop_time,created_time,updated_time",
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
        return meta_get_all_pages(f"{account_id}/campaigns", token, params=params, max_pages=max_pages)

    return meta_call("GET", f"{account_id}/campaigns", token, params=params)


@router.post("/campaigns")
async def create_campaign(body: CampaignCreateRequest, token: str = Depends(resolve_access_token)):
    account_id = normalize_account_id(body.account_id)
    payload = {
        "name": body.name,
        "objective": body.objective,
        "status": body.status,
        "special_ad_categories": body.special_ad_categories,
        "is_adset_budget_sharing_enabled": body.is_adset_budget_sharing_enabled,
    }
    if body.buying_type:
        payload["buying_type"] = body.buying_type
    payload.update(body.extra_params)

    return meta_call("POST", f"{account_id}/campaigns", token, data=payload)
