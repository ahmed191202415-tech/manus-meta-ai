from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.auth import resolve_access_token
from app.core.meta_client import meta_call
from app.core.oauth_store import (
    create_comment_automation_rule,
    create_comment_post_alias,
    delete_comment_automation_rule,
    find_meta_connection_by_access_token,
    get_active_meta_connection_for_tenant,
    get_app_token_data,
    get_comment_automation_rule,
    list_comment_automation_logs,
    list_comment_automation_rules,
    list_comment_post_aliases,
    list_comment_webhook_events,
    list_unmapped_comment_posts,
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
    try:
        return meta_call(
            "POST",
            f"{page_id}/subscribed_apps",
            page_token,
            data={"subscribed_fields": "feed"},
        )
    except HTTPException as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                "message": "Could not subscribe this Facebook Page to comment webhooks.",
                "operation": "subscribe_page_webhook",
                "page_id": page_id,
                "required_permission": "pages_manage_metadata",
                "next_step": (
                    "Confirm that this is the Page ID returned by list_pages, not a post ID. "
                    "Then reconnect Meta so pages_manage_metadata is granted and try subscribe_page again."
                ),
                "meta_error": exc.detail,
            },
        ) from exc


def _resolve_managed_page(page_id: str, user_token: str) -> tuple[dict, str]:
    clean_page_id = str(page_id or "").strip()
    payload = meta_call(
        "GET",
        "me/accounts",
        user_token,
        params={"fields": "id,name,access_token", "limit": 200},
    )
    for page in payload.get("data", []):
        if str(page.get("id") or "").strip() != clean_page_id:
            continue
        page_token = str(page.get("access_token") or "").strip()
        if not page_token:
            break
        return page, page_token
    raise HTTPException(
        status_code=403,
        detail={
            "message": "The supplied page_id is not available among the Facebook Pages managed by this connection.",
            "page_id": clean_page_id,
            "next_step": "Call list_pages and use the id returned for the Page itself. Do not use a post ID or ad ID.",
        },
    )


def _page_preflight(page_id: str, user_token: str) -> dict:
    clean_page_id = str(page_id or "").strip()
    try:
        accounts_payload = meta_call(
            "GET",
            "me/accounts",
            user_token,
            params={"fields": "id,name,access_token", "limit": 200},
        )
        accounts_error = None
    except HTTPException as exc:
        accounts_payload = {"data": []}
        accounts_error = exc.detail

    try:
        permissions_payload = meta_call("GET", "me/permissions", user_token)
        permissions_error = None
    except HTTPException as exc:
        permissions_payload = {"data": []}
        permissions_error = exc.detail

    pages = accounts_payload.get("data", [])
    visible_pages = [
        {"id": str(page.get("id") or ""), "name": str(page.get("name") or "")}
        for page in pages
    ]
    selected_page = next(
        (page for page in pages if str(page.get("id") or "").strip() == clean_page_id),
        None,
    )
    page_token = str((selected_page or {}).get("access_token") or "").strip()
    granted_permissions = sorted(
        str(item.get("permission") or "")
        for item in permissions_payload.get("data", [])
        if item.get("status") == "granted"
    )
    required_permissions = ["pages_show_list", "pages_read_engagement", "pages_manage_metadata"]
    return {
        "page_id": clean_page_id,
        "page_visible": bool(selected_page),
        "page_token_available": bool(page_token),
        "visible_pages": visible_pages,
        "granted_permissions": granted_permissions,
        "missing_required_permissions": [
            permission for permission in required_permissions if permission not in granted_permissions
        ],
        "accounts_error": accounts_error,
        "permissions_error": permissions_error,
        "_page_token": page_token,
    }


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
        _, page_token = _resolve_managed_page(page_id, token)
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

    if body.action == "list_unmapped_posts":
        return {
            "tenant_id": tenant_id,
            "page_id": body.page_id,
            "unmapped_posts": list_unmapped_comment_posts(tenant_id, page_id=body.page_id, limit=body.limit),
            "next_step": "Review the canonical post_id and link it to an existing rule with link_post_alias.",
        }

    if body.action == "list_post_aliases":
        return {
            "tenant_id": tenant_id,
            "page_id": body.page_id,
            "post_aliases": list_comment_post_aliases(tenant_id, page_id=body.page_id),
        }

    if body.action == "link_post_alias":
        rule = get_comment_automation_rule(tenant_id, str(body.rule_id or ""))
        if not rule:
            raise HTTPException(status_code=404, detail="Comment automation rule was not found.")
        if str(rule.get("page_id") or "").strip() != str(body.page_id or "").strip():
            raise HTTPException(status_code=400, detail="The rule and canonical post must belong to the same Facebook Page.")
        alias = create_comment_post_alias(
            tenant_id=tenant_id,
            rule_id=str(body.rule_id or ""),
            page_id=str(body.page_id or ""),
            canonical_post_id=str(body.post_id or ""),
            source_post_id=body.source_post_id or rule.get("post_id"),
        )
        return {
            "success": True,
            "message": "The canonical Page post alias was approved. New comments on this post will use the linked automation rule.",
            "post_alias": alias,
        }

    if body.action == "diagnose_page":
        page_id = str(body.page_id or "").strip()
        preflight = _page_preflight(page_id, token)
        page_token = str(preflight.pop("_page_token") or "")
        subscription = None
        subscription_error = None
        if page_token:
            try:
                _select_page(tenant_id, page_id, page_token)
                subscription = meta_call("GET", f"{page_id}/subscribed_apps", page_token)
            except HTTPException as exc:
                subscription_error = exc.detail
        rules = list_comment_automation_rules(tenant_id, page_id=page_id)
        deliveries = list_comment_webhook_events(page_id=page_id, limit=body.limit)
        executions = list_comment_automation_logs(tenant_id, limit=body.limit)
        aliases = list_comment_post_aliases(tenant_id, page_id=page_id)
        unmapped_posts = list_unmapped_comment_posts(tenant_id, page_id=page_id, limit=body.limit)
        return {
            "tenant_id": tenant_id,
            "page_id": page_id,
            "diagnosis": {
                **preflight,
                "page_subscribed_apps": subscription,
                "page_subscription_error": subscription_error,
                "enabled_rule_count": len([rule for rule in rules if rule.get("enabled")]),
                "webhook_delivery_count": len(deliveries),
                "automation_execution_count": len(executions),
                "next_check": (
                    "If webhook_delivery_count is zero after a new external comment, verify the Meta Page webhook feed subscription. "
                    "If a delivery exists, inspect delivery_status. If an execution exists, inspect error_message."
                ),
            },
            "rules": rules,
            "recent_webhook_deliveries": deliveries,
            "recent_automation_executions": executions,
            "post_aliases": aliases,
            "unmapped_posts": unmapped_posts,
        }

    raise HTTPException(status_code=400, detail="Unsupported comment automation action.")
