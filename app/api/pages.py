from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends

from app.config import DEFAULT_PAGE_LIMIT, DEFAULT_MAX_PAGES
from app.core.auth import resolve_access_token
from app.core.pagination import meta_get_all_pages
from app.core.meta_client import meta_call
from app.core.token_router import resolve_page_token_for_page_id
from app.schemas.page_requests import (
    PagePostCreateRequest,
    CommentReplyRequest,
    CommentHideRequest,
    ObjectDeleteRequest,
)

router = APIRouter(tags=["pages"])


@router.get("/pages")
async def list_pages(
    user_id: str = "me",
    fields: str = "id,name,category,fan_count,followers_count,access_token,instagram_business_account,picture{url}",
    limit: int = DEFAULT_PAGE_LIMIT,
    fetch_all: bool = False,
    max_pages: int = 10,
    token: str = Depends(resolve_access_token),
):
    params = {"fields": fields, "limit": limit}
    if fetch_all:
        return meta_get_all_pages(f"{user_id}/accounts", token, params=params, max_pages=max_pages)
    return meta_call("GET", f"{user_id}/accounts", token, params=params)


@router.get("/page_posts")
async def list_page_posts(
    page_id: str,
    fields: str = "id,message,created_time,updated_time,permalink_url,status_type,full_picture,attachments,insights.metric(post_impressions,post_engaged_users)",
    limit: int = DEFAULT_PAGE_LIMIT,
    after: Optional[str] = None,
    fetch_all: bool = False,
    max_pages: int = DEFAULT_MAX_PAGES,
    token: str = Depends(resolve_access_token),
):
    page_token = resolve_page_token_for_page_id(token, page_id)
    params = {"fields": fields, "limit": limit}
    if after:
        params["after"] = after
    if fetch_all:
        return meta_get_all_pages(f"{page_id}/posts", page_token, params=params, max_pages=max_pages)
    return meta_call("GET", f"{page_id}/posts", page_token, params=params)


@router.post("/page_posts")
async def create_page_post(body: PagePostCreateRequest, token: str = Depends(resolve_access_token)):
    page_token = resolve_page_token_for_page_id(token, body.page_id)

    payload: Dict[str, Any] = {}
    if body.message is not None:
        payload["message"] = body.message
    if body.link is not None:
        payload["link"] = body.link
    if body.published is not None:
        payload["published"] = body.published
    if body.scheduled_publish_time is not None:
        payload["scheduled_publish_time"] = body.scheduled_publish_time
    if body.attached_media is not None:
        payload["attached_media"] = body.attached_media
    payload.update(body.extra_params)

    return meta_call("POST", f"{body.page_id}/feed", page_token, data=payload)


@router.delete("/page_posts/{post_id}")
async def delete_page_post(post_id: str, page_id: str, token: str = Depends(resolve_access_token)):
    page_token = resolve_page_token_for_page_id(token, page_id)
    return meta_call("DELETE", post_id, page_token)


@router.get("/page_comments")
async def list_page_comments(
    object_id: str,
    page_id: str,
    fields: str = "id,from,message,created_time,like_count,comment_count,is_hidden,parent{id,message}",
    limit: int = DEFAULT_PAGE_LIMIT,
    after: Optional[str] = None,
    fetch_all: bool = False,
    max_pages: int = DEFAULT_MAX_PAGES,
    token: str = Depends(resolve_access_token),
):
    page_token = resolve_page_token_for_page_id(token, page_id)
    params = {"fields": fields, "limit": limit}
    if after:
        params["after"] = after
    if fetch_all:
        return meta_get_all_pages(f"{object_id}/comments", page_token, params=params, max_pages=max_pages)
    return meta_call("GET", f"{object_id}/comments", page_token, params=params)


@router.post("/page_comments/{comment_id}/reply")
async def reply_to_comment(
    comment_id: str,
    page_id: str,
    body: CommentReplyRequest,
    token: str = Depends(resolve_access_token),
):
    page_token = resolve_page_token_for_page_id(token, page_id)
    payload: Dict[str, Any] = {"message": body.message}
    payload.update(body.extra_params)
    return meta_call("POST", f"{comment_id}/comments", page_token, data=payload)


@router.post("/page_comments/{comment_id}/hide")
async def hide_comment(
    comment_id: str,
    page_id: str,
    body: CommentHideRequest,
    token: str = Depends(resolve_access_token),
):
    page_token = resolve_page_token_for_page_id(token, page_id)
    payload = {"is_hidden": body.is_hidden}
    return meta_call("POST", comment_id, page_token, data=payload)


@router.delete("/page_comments/{comment_id}")
async def delete_comment(comment_id: str, page_id: str, token: str = Depends(resolve_access_token)):
    page_token = resolve_page_token_for_page_id(token, page_id)
    return meta_call("DELETE", comment_id, page_token)


@router.post("/objects/{object_id}/delete")
async def delete_object_raw(
    object_id: str,
    page_id: str,
    body: ObjectDeleteRequest,
    token: str = Depends(resolve_access_token),
):
    page_token = resolve_page_token_for_page_id(token, page_id)
    payload = dict(body.extra_params or {})
    payload["method"] = "delete"
    return meta_call("POST", object_id, page_token, data=payload)


@router.get("/page_insights")
async def page_insights(
    page_id: str,
    metric: str,
    period: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    token: str = Depends(resolve_access_token),
):
    page_token = resolve_page_token_for_page_id(token, page_id)

    params: Dict[str, Any] = {"metric": metric}
    if period:
        params["period"] = period
    if since:
        params["since"] = since
    if until:
        params["until"] = until

    return meta_call("GET", f"{page_id}/insights", page_token, params=params)


@router.get("/instagram_accounts")
async def instagram_accounts(page_id: str, token: str = Depends(resolve_access_token)):
    page_token = resolve_page_token_for_page_id(token, page_id)
    return meta_call(
        "GET",
        page_id,
        page_token,
        params={"fields": "instagram_business_account{id,username,profile_picture_url,followers_count,media_count}"},
    )