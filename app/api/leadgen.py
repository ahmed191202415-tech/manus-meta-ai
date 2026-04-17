from typing import Optional
from fastapi import APIRouter, Depends

from app.config import DEFAULT_PAGE_LIMIT, DEFAULT_MAX_PAGES
from app.core.auth import resolve_access_token
from app.core.pagination import meta_get_all_pages
from app.core.meta_client import meta_call

router = APIRouter(tags=["leadgen"])


@router.get("/leadgen_forms")
async def list_leadgen_forms(
    page_id: str,
    fields: str = "id,name,status,locale,created_time,leads_count,questions,privacy_policy_url,follow_up_action_url",
    limit: int = DEFAULT_PAGE_LIMIT,
    after: Optional[str] = None,
    fetch_all: bool = False,
    max_pages: int = DEFAULT_MAX_PAGES,
    token: str = Depends(resolve_access_token),
):
    params = {"fields": fields, "limit": limit}
    if after:
        params["after"] = after
    if fetch_all:
        return meta_get_all_pages(f"{page_id}/leadgen_forms", token, params=params, max_pages=max_pages)
    return meta_call("GET", f"{page_id}/leadgen_forms", token, params=params)


@router.get("/leads")
async def list_leads(
    form_id: str,
    fields: str = "id,created_time,field_data,platform,ad_id,form_id",
    limit: int = DEFAULT_PAGE_LIMIT,
    after: Optional[str] = None,
    fetch_all: bool = False,
    max_pages: int = DEFAULT_MAX_PAGES,
    token: str = Depends(resolve_access_token),
):
    params = {"fields": fields, "limit": limit}
    if after:
        params["after"] = after
    if fetch_all:
        return meta_get_all_pages(f"{form_id}/leads", token, params=params, max_pages=max_pages)
    return meta_call("GET", f"{form_id}/leads", token, params=params)
