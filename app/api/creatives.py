from typing import Optional
from fastapi import APIRouter, Depends

from app.config import DEFAULT_PAGE_LIMIT, DEFAULT_MAX_PAGES
from app.core.auth import resolve_access_token
from app.core.pagination import meta_get_all_pages
from app.core.meta_client import meta_call, normalize_account_id
from app.schemas.meta_requests import CreativeCreateRequest

router = APIRouter(tags=["creatives"])


@router.get("/adcreatives")
async def list_adcreatives(
    account_id: str,
    fields: str = "id,name,object_story_spec,asset_feed_spec,effective_object_story_id,thumbnail_url,image_hash,url_tags,created_time",
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
        return meta_get_all_pages(f"{account_id}/adcreatives", token, params=params, max_pages=max_pages)

    return meta_call("GET", f"{account_id}/adcreatives", token, params=params)


@router.post("/adcreatives")
async def create_adcreative(body: CreativeCreateRequest, token: str = Depends(resolve_access_token)):
    account_id = normalize_account_id(body.account_id)

    payload = {"name": body.name}

    if body.object_story_spec is not None:
        payload["object_story_spec"] = body.object_story_spec
    if body.asset_feed_spec is not None:
        payload["asset_feed_spec"] = body.asset_feed_spec
    if body.degrees_of_freedom_spec is not None:
        payload["degrees_of_freedom_spec"] = body.degrees_of_freedom_spec
    if body.url_tags is not None:
        payload["url_tags"] = body.url_tags

    payload.update(body.extra_params)

    return meta_call("POST", f"{account_id}/adcreatives", token, data=payload)
