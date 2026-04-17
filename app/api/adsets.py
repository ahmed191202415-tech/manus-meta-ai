from typing import Optional
from fastapi import APIRouter, Depends

from app.config import DEFAULT_PAGE_LIMIT, DEFAULT_MAX_PAGES
from app.core.auth import resolve_access_token
from app.core.pagination import meta_get_all_pages
from app.core.meta_client import meta_call, normalize_account_id
from app.schemas.meta_requests import AdSetCreateRequest

router = APIRouter(tags=["adsets"])


@router.get("/adsets")
async def list_adsets(
    account_id: str,
    fields: str = "id,name,campaign_id,status,effective_status,daily_budget,lifetime_budget,bid_strategy,optimization_goal,billing_event,start_time,end_time,targeting,promoted_object,attribution_spec,created_time,updated_time",
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
        return meta_get_all_pages(f"{account_id}/adsets", token, params=params, max_pages=max_pages)

    return meta_call("GET", f"{account_id}/adsets", token, params=params)


@router.post("/adsets")
async def create_adset(body: AdSetCreateRequest, token: str = Depends(resolve_access_token)):
    account_id = normalize_account_id(body.account_id)

    payload = {
        "name": body.name,
        "campaign_id": body.campaign_id,
        "optimization_goal": body.optimization_goal,
        "billing_event": body.billing_event,
        "status": body.status,
        "targeting": body.targeting,
    }

    if body.bid_strategy:
        payload["bid_strategy"] = body.bid_strategy
    if body.daily_budget is not None:
        payload["daily_budget"] = body.daily_budget
    if body.lifetime_budget is not None:
        payload["lifetime_budget"] = body.lifetime_budget
    if body.bid_amount is not None:
        payload["bid_amount"] = body.bid_amount
    if body.promoted_object is not None:
        payload["promoted_object"] = body.promoted_object
    if body.start_time:
        payload["start_time"] = body.start_time
    if body.end_time:
        payload["end_time"] = body.end_time
    if body.attribution_spec is not None:
        payload["attribution_spec"] = body.attribution_spec

    payload.update(body.extra_params)

    return meta_call("POST", f"{account_id}/adsets", token, data=payload)
