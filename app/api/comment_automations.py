from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.auth import resolve_access_token
from app.core.meta_client import meta_call
from app.core.oauth_store import (
    create_comment_automation_rule,
    delete_comment_automation_rule,
    find_meta_connection_by_access_token,
    get_active_meta_connection_for_tenant,
    get_app_token_data,
    list_comment_automation_logs,
    list_comment_automation_rules,
    set_comment_automation_rule_enabled,
    set_selected_page,
)
from app.core.token_router import resolve_page_token_for_page_id
from app.schemas.comment_automation_requests import CommentAutomationManageRequest

router = APIRouter(prefix="/comment_automations", tags=["comment automations"])


def _bearer_token(request: Request) -> str:
    authorization = str(request.headers.get("authorization") or "")
    if authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return ""


def _resolve_tenant_id(request: Request, supplied_tenant_id: str | None, resolved_meta_token: str) -> str:
    session_tenant_id = str(request.session.get("tenant_id") or "").strip()
    bearer = _bearer_token(request)
    app_data = get_app_token_data(bearer) if bearer.startswith("app_") else None
    token_connection = find_meta_connection_by_access_token(resolved_meta_token)
    authenticated_tenant_id = str(
        (app_data or {}).get("tenant_id")
        or (token_connection or {}).get("tenant_id")
        or session_tenant_id
        or ""
    ).strip()
    clean_supplied = str(supplied_tenant_id or "").strip()
    if clean_supplied and authenticated_tenant_id and clean_supplied != authenticated_tenant_id:
        raise HTTPException(status_code=403, detail="The requested tenant does not match the authenticated Meta connection.")
    tenant_id = clean_supplied or authenticated_tenant_id
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Tenant is required. Connect Meta first.")
    return tenant_id


def _subscribe_page(page_id: str, page_token: str) -> dict:
    return meta_call(
        "POST",
        f"{page_id}/subscribed_apps",
        page_token,
        data={"subscribed_fields": "feed"},
    )


def _select_page(tenant_id: str, page_id: str, page_token: str) -> None:
    connection = get_active_meta_connection_for_tenant(tenant_id)
    if not connection:
        raise HTTPException(status_code=401, detail="Meta is not connected for this tenant.")
    page = meta_call("GET", page_id, page_token, params={"fields": "id,name"})
    set_selected_page(
        tenant_id=tenant_id,
        meta_user_id=connection["meta_user_id"],
        page_id=page_id,
        page_name=str(page.get("name") or ""),
        page_access_token=page_token,
    )


@router.post("/manage")
async def manage_comment_automations(
    body: CommentAutomationManageRequest,
    request: Request,
    token: str = Depends(resolve_access_token),
):
    tenant_id = _resolve_tenant_id(request, body.tenant_id, token)

    if body.action == "list_pages":
        return meta_call("GET", "me/accounts", token, params={"fields": "id,name,category", "limit": body.limit})

    if body.action == "list_posts":
        page_token = resolve_page_token_for_page_id(token, body.page_id or "")
        _select_page(tenant_id, str(body.page_id or ""), page_token)
        return meta_call(
            "GET",
            f"{body.page_id}/posts",
            page_token,
            params={"fields": "id,message,created_time,permalink_url", "limit": body.limit},
        )

    if body.action == "list_comments":
        page_token = resolve_page_token_for_page_id(token, body.page_id or "")
        _select_page(tenant_id, str(body.page_id or ""), page_token)
        return meta_call(
            "GET",
            f"{body.post_id}/comments",
            page_token,
            params={"fields": "id,from,message,created_time,like_count,comment_count,is_hidden", "limit": body.limit},
        )

    if body.action in {"subscribe_page", "create_rule"}:
        page_id = str(body.page_id or "").strip()
        page_token = resolve_page_token_for_page_id(token, page_id)
        subscription = _subscribe_page(page_id, page_token)
        _select_page(tenant_id, page_id, page_token)
        if body.action == "subscribe_page":
            return {
                "success": True,
                "action": "subscribe_page",
                "tenant_id": tenant_id,
                "page_id": page_id,
                "subscription": subscription,
            }
        rule = create_comment_automation_rule(
            tenant_id=tenant_id,
            page_id=page_id,
            page_access_token=page_token,
            post_id=str(body.post_id or "").strip(),
            keyword=body.keyword,
            match_mode=body.match_mode,
            public_reply_message=body.public_reply_message,
            private_reply_message=body.private_reply_message,
            hide_comment=body.hide_comment,
        )
        rule.pop("page_access_token", None)
        return {
            "success": True,
            "action": "create_rule",
            "subscription": subscription,
            "rule": rule,
        }

    if body.action == "list_rules":
        return {
            "tenant_id": tenant_id,
            "rules": list_comment_automation_rules(tenant_id, page_id=body.page_id, post_id=body.post_id),
        }

    if body.action in {"enable_rule", "disable_rule"}:
        enabled = body.action == "enable_rule"
        rule = set_comment_automation_rule_enabled(tenant_id, str(body.rule_id or ""), enabled)
        if not rule:
            raise HTTPException(status_code=404, detail="Comment automation rule was not found.")
        rule.pop("page_access_token", None)
        return {"success": True, "rule": rule}

    if body.action == "delete_rule":
        delete_comment_automation_rule(tenant_id, str(body.rule_id or ""))
        return {"success": True, "rule_id": body.rule_id, "message": "Comment automation rule was deleted."}

    if body.action == "list_logs":
        return {"tenant_id": tenant_id, "logs": list_comment_automation_logs(tenant_id, limit=body.limit)}

    raise HTTPException(status_code=400, detail="Unsupported comment automation action.")
