from typing import Optional
from fastapi import APIRouter, Depends

from app.config import DEFAULT_PAGE_LIMIT, DEFAULT_MAX_PAGES
from app.core.auth import resolve_access_token
from app.core.pagination import meta_get_all_pages
from app.core.meta_client import meta_call, normalize_account_id
from app.schemas.meta_requests import CustomAudienceCreateRequest, AudienceUsersRequest

router = APIRouter(tags=["audiences"])


@router.get("/custom_audiences")
async def list_custom_audiences(
    account_id: str,
    fields: str = "id,name,description,subtype,approximate_count,time_updated,retention_days,rule,lookalike_spec,delivery_status,operation_status",
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
        return meta_get_all_pages(f"{account_id}/customaudiences", token, params=params, max_pages=max_pages)
    return meta_call("GET", f"{account_id}/customaudiences", token, params=params)


@router.post("/custom_audiences")
async def create_custom_audience(body: CustomAudienceCreateRequest, token: str = Depends(resolve_access_token)):
    account_id = normalize_account_id(body.account_id)
    payload = {
        "name": body.name,
        "subtype": body.subtype,
    }
    if body.description is not None:
        payload["description"] = body.description
    if body.customer_file_source is not None:
        payload["customer_file_source"] = body.customer_file_source
    if body.rule is not None:
        payload["rule"] = body.rule
    if body.prefill is not None:
        payload["prefill"] = body.prefill
    if body.retention_days is not None:
        payload["retention_days"] = body.retention_days
    if body.lookalike_spec is not None:
        payload["lookalike_spec"] = body.lookalike_spec
    if body.pixel_id is not None:
        payload["pixel_id"] = body.pixel_id
    payload.update(body.extra_params)
    return meta_call("POST", f"{account_id}/customaudiences", token, data=payload)


@router.post("/custom_audiences/{audience_id}/users")
async def custom_audience_users(audience_id: str, body: AudienceUsersRequest, token: str = Depends(resolve_access_token)):
    return meta_call("POST", f"{audience_id}/users", token, data=body.payload)
