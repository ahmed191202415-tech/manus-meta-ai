import hashlib
import hmac
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request

from app.config import IS_PRODUCTION, META_APP_SECRET, META_WEBHOOK_VERIFY_TOKEN
from app.core.meta_client import meta_call
from app.core.oauth_store import (
    begin_comment_automation_log,
    find_tenant_meta_app_by_webhook_verify_token,
    finish_comment_automation_log,
    get_active_meta_connection_for_tenant,
    get_tenant_meta_app,
    list_enabled_comment_automation_rules_for_page,
    list_enabled_comment_automation_rules_for_alias,
    list_enabled_comment_automation_rules_for_post,
    save_comment_webhook_event,
)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _is_valid_verify_token(token: str | None) -> bool:
    clean_token = str(token or "").strip()
    if not clean_token:
        return False
    if META_WEBHOOK_VERIFY_TOKEN and clean_token == META_WEBHOOK_VERIFY_TOKEN:
        return True
    try:
        return bool(find_tenant_meta_app_by_webhook_verify_token(clean_token))
    except Exception:
        return False


def extract_comment_events(payload: dict[str, Any]) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    for entry in payload.get("entry", []):
        page_id = str(entry.get("id") or "").strip()
        for change in entry.get("changes", []):
            value = change.get("value") or {}
            if change.get("field") != "feed":
                continue
            if value.get("item") != "comment" or value.get("verb") != "add":
                continue
            comment_id = str(value.get("comment_id") or "").strip()
            post_id = str(value.get("post_id") or "").strip()
            commenter_id = str((value.get("from") or {}).get("id") or "").strip()
            if not page_id or not post_id or not comment_id or commenter_id == page_id:
                continue
            events.append(
                {
                    "page_id": page_id,
                    "post_id": post_id,
                    "comment_id": comment_id,
                    "commenter_id": commenter_id,
                    "message": str(value.get("message") or "").strip(),
                }
            )
    return events


def rule_matches_comment(rule: dict, event: dict) -> bool:
    if rule.get("match_mode") == "all_comments":
        return True
    keyword = str(rule.get("keyword") or "").strip().casefold()
    return bool(keyword and keyword in str(event.get("message") or "").casefold())


def is_valid_meta_webhook_signature(payload: bytes, signature: str | None, events: list[dict[str, str]]) -> bool:
    clean_signature = str(signature or "").strip()
    if not clean_signature.startswith("sha256="):
        return not IS_PRODUCTION
    expected_digest = clean_signature.split("=", 1)[1]
    secrets = {str(META_APP_SECRET or "").strip()}
    for page_id in {event["page_id"] for event in events}:
        for rule in list_enabled_comment_automation_rules_for_page(page_id):
            app = get_tenant_meta_app(str(rule.get("tenant_id") or ""))
            secrets.add(str((app or {}).get("meta_app_secret") or "").strip())
    for secret in secrets:
        if not secret:
            continue
        actual_digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
        if hmac.compare_digest(actual_digest, expected_digest):
            return True
    return False


def _meta_app_secret_for_rule(rule: dict) -> str | None:
    connection = get_active_meta_connection_for_tenant(str(rule.get("tenant_id") or ""))
    if not connection or connection.get("connection_mode") == "manual_token":
        return None
    app = get_tenant_meta_app(str(rule.get("tenant_id") or ""))
    return str((app or {}).get("meta_app_secret") or "").strip() or None


def _is_missing_private_reply_object(exc: Exception) -> bool:
    if not isinstance(exc, HTTPException) or not isinstance(exc.detail, dict):
        return False
    return exc.detail.get("code") == 100 and exc.detail.get("error_subcode") == 33


def _private_reply_attempts(event: dict, message: str) -> list[tuple[str, str, dict]]:
    comment_id = str(event.get("comment_id") or "").strip()
    page_id = str(event.get("page_id") or "").strip()
    short_comment_id = comment_id.rsplit("_", 1)[-1]
    attempts = [
        ("comment_private_replies", f"{comment_id}/private_replies", {"message": message}),
    ]
    if short_comment_id and short_comment_id != comment_id:
        attempts.append(("short_comment_private_replies", f"{short_comment_id}/private_replies", {"message": message}))
    attempts.append(
        (
            "page_messages_comment_recipient",
            f"{page_id}/messages",
            {"recipient": {"comment_id": comment_id}, "message": {"text": message}},
        )
    )
    return attempts


def send_facebook_private_reply(event: dict, message: str, page_token: str, app_secret: str | None = None) -> dict:
    failures = []
    for mode, path, data in _private_reply_attempts(event, message):
        try:
            response = meta_call("POST", path, page_token, data=data, app_secret=app_secret)
            return {"mode": mode, "response": response}
        except Exception as exc:
            failures.append({"mode": mode, "path": path, "error": str(exc)})
            if not _is_missing_private_reply_object(exc):
                raise
    raise HTTPException(
        status_code=400,
        detail={
            "message": "All supported Facebook private reply request formats were rejected.",
            "attempts": failures,
        },
    )


def _process_rule(rule: dict, event: dict) -> None:
    log = begin_comment_automation_log(rule, event)
    if not log:
        return
    page_token = str(rule.get("page_access_token") or "").strip()
    app_secret = _meta_app_secret_for_rule(rule)
    public_status = "skipped"
    private_status = "skipped"
    hide_status = "skipped"
    errors: list[str] = []

    if not page_token:
        errors.append("Page access token is missing.")
    else:
        if rule.get("public_reply_message"):
            try:
                meta_call(
                    "POST",
                    f"{event['comment_id']}/comments",
                    page_token,
                    data={"message": rule["public_reply_message"]},
                    app_secret=app_secret,
                )
                public_status = "sent"
            except Exception as exc:
                public_status = "failed"
                errors.append(f"Public reply failed: {exc}")

        if rule.get("private_reply_message"):
            try:
                send_facebook_private_reply(event, rule["private_reply_message"], page_token, app_secret=app_secret)
                private_status = "sent"
            except Exception as exc:
                private_status = "failed"
                errors.append(f"Private reply failed: {exc}")

        if rule.get("hide_comment"):
            try:
                meta_call("POST", event["comment_id"], page_token, data={"is_hidden": True}, app_secret=app_secret)
                hide_status = "hidden"
            except Exception as exc:
                hide_status = "failed"
                errors.append(f"Hide comment failed: {exc}")

    finish_comment_automation_log(
        str(log["log_id"]),
        {
            "public_reply_status": public_status,
            "private_reply_status": private_status,
            "hide_status": hide_status,
            "error_message": " | ".join(errors)[:2000],
        },
    )


def process_comment_events(payload: dict[str, Any]) -> None:
    for event in extract_comment_events(payload):
        rules = list_enabled_comment_automation_rules_for_post(event["page_id"], event["post_id"])
        if not rules:
            rules = list_enabled_comment_automation_rules_for_alias(event["page_id"], event["post_id"])
        matched_rules = [rule for rule in rules if rule_matches_comment(rule, event)]
        tenant_id = str((matched_rules or rules or [{}])[0].get("tenant_id") or "").strip() or None
        if not rules:
            save_comment_webhook_event(
                event,
                "unmapped_ad_post",
                diagnostic_message=(
                    "Webhook arrived from a canonical Page post ID that has no direct rule or approved alias. "
                    "Review the unmapped post and link it to an existing rule before automatic replies start."
                ),
            )
            continue
        if not matched_rules:
            save_comment_webhook_event(
                event,
                "keyword_not_matched",
                diagnostic_message="Webhook arrived and the post rule exists, but the comment did not contain the configured keyword.",
                tenant_id=tenant_id,
            )
            continue
        save_comment_webhook_event(
            event,
            "processing",
            matched_rule_count=len(matched_rules),
            diagnostic_message="Webhook arrived and matching automation rules are being executed.",
            tenant_id=tenant_id,
        )
        for rule in matched_rules:
            _process_rule(rule, event)


@router.get("/meta")
async def verify_webhook(
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
):
    if hub_mode == "subscribe" and _is_valid_verify_token(hub_verify_token):
        return int(hub_challenge) if hub_challenge and hub_challenge.isdigit() else (hub_challenge or "")
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/meta")
async def receive_webhook(request: Request, background_tasks: BackgroundTasks):
    raw_payload = await request.body()
    payload = await request.json()
    events = extract_comment_events(payload)
    if not is_valid_meta_webhook_signature(raw_payload, request.headers.get("x-hub-signature-256"), events):
        raise HTTPException(status_code=403, detail="Invalid Meta webhook signature.")
    background_tasks.add_task(process_comment_events, payload)
    return {"ok": True}
