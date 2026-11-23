"""Google Ads API v25 gateway for existing GPT Actions (no schema change).

Uses the existing per-tenant Google OAuth connection. Never accepts an access
token, refresh token or tenant identity from natural-language GPT inputs.
"""
from __future__ import annotations

import logging
import time
import os
import re
import secrets
from urllib.parse import quote

import requests
from fastapi import HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import PUBLIC_BASE_URL, SESSION_SECRET
from app.core.google_ads_errors import decode_google_ads_error, safe_request_id
from app.core.google_ads_reporting import REPORTS, prepare_report, finalize_report, aggregate_metrics
from app.core.google_ads_query import prepare_query, finalize_query
from app.core.ga4_client import get_google_credentials_for_tenant
from app.core.oauth_store import (
    consume_auth_code, create_auth_code, get_active_google_connection_for_tenant,
    get_app_token_data,
)

API_VERSION = "v25"
BASE = f"https://googleads.googleapis.com/{API_VERSION}"
ADS_SCOPE = "https://www.googleapis.com/auth/adwords"
MAX_ROWS = 300
DURATIONS = {"TODAY", "YESTERDAY", "LAST_7_DAYS", "LAST_14_DAYS", "LAST_30_DAYS", "THIS_MONTH", "LAST_MONTH", "ALL_TIME"}
WRITABLE_OPERATIONS = {
    "campaignOperation", "campaignBudgetOperation", "adGroupOperation",
    "adGroupCriterionOperation", "adGroupAdOperation", "campaignCriterionOperation",
    "customerNegativeCriterionOperation", "adOperation", "assetOperation",
    "campaignAssetOperation", "adGroupAssetOperation", "conversionActionOperation",
    "biddingStrategyOperation", "sharedSetOperation", "campaignSharedSetOperation",
}
ID_RE = re.compile(r"^[0-9]{10}$")
_RESOURCE_RE = re.compile(r"^customers/([0-9]{10})(?:/|$)")


def _signer(salt: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(SESSION_SECRET, salt=salt)


def _required_app_identity(request: Request) -> dict:
    bearer = request.headers.get("authorization", "")
    if not bearer.lower().startswith("bearer "):
        raise HTTPException(401, "Connect GPT Actions OAuth before using Google Ads.")
    token = bearer.split(" ", 1)[1].strip()
    if not token.startswith("app_"):
        raise HTTPException(401, "An authorized GPT OAuth session is required for Google Ads.")
    try:
        identity = get_app_token_data(token)
    except Exception:
        raise HTTPException(
            503, "Application session verification is temporarily unavailable. Retry without signing in again."
        ) from None
    if not identity:
        raise HTTPException(401, "Your GPT connection expired. Reconnect the GPT Action.")
    return identity


def _customer_id(value: object) -> str:
    clean = str(value or "").replace("-", "").strip()
    if not ID_RE.fullmatch(clean):
        raise HTTPException(422, "customer_id must be the 10-digit Google Ads customer ID.")
    return clean


def _connect_url(tenant_id: str) -> str:
    signed = _signer("google-ads-connect-v1").dumps({"tenant_id": tenant_id})
    return (PUBLIC_BASE_URL or "").rstrip("/") + "/auth/google/ads/connect?ticket=" + quote(signed)


def _credentials(tenant_id: str) -> dict:
    try:
        existing = get_active_google_connection_for_tenant(tenant_id)
    except Exception:
        raise HTTPException(503, "Google connection database is unavailable.")
    if not existing or existing.get("connection_mode") != "oauth" or ADS_SCOPE not in str(existing.get("scopes") or "").split():
        raise HTTPException(409, {
            "message": "Google Ads OAuth scope isn't connected. Authorize Google Ads first.",
            "connect_url": _connect_url(tenant_id),
            "required_scope": ADS_SCOPE,
        })
    try:
        return get_google_credentials_for_tenant(tenant_id)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(502, "Google OAuth refresh failed.")


def _headers(credentials: dict, manager_id: object = None) -> dict:
    headers = {
        "Authorization": "Bearer " + str(credentials["access_token"]),
        "Content-Type": "application/json",
    }
    login = manager_id or os.getenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID")
    if login:
        headers["login-customer-id"] = _customer_id(login)
    # Google Ads developer tokens were sunset in September 2026.
    # This legacy header remains optional for older Google Cloud projects.
    legacy = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN", "").strip()
    if legacy:
        headers["developer-token"] = legacy
    return headers


def _api(tenant_id: str, method: str, path: str, body: dict | None = None, *, manager_id=None) -> dict | list:
    """Tenant-scoped REST transport. Only read-only calls can be retried."""
    credentials = _credentials(tenant_id)
    read_only = method.upper() == "GET" or path.endswith(("/googleAds:search", "/googleAds:searchStream"))
    applying_write = path.endswith("/googleAds:mutate") and (body or {}).get("validateOnly") is not True
    attempts = 2 if read_only else 1
    response = None
    for attempt in range(attempts):
        try:
            response = requests.request(
                method, BASE + path, headers=_headers(credentials, manager_id),
                json=body, timeout=45,
            )
        except requests.RequestException:
            if read_only and attempt + 1 < attempts:
                time.sleep(0.5)
                continue
            detail = {
                "origin": "google_ads_transport", "http_status": 502,
                "message": "Google Ads API could not be reached.",
                "retryable": read_only, "outcome_unknown": applying_write,
                "next_step": (
                    "Retry the read after connectivity recovers."
                    if not applying_write else
                    "Do not repeat this mutation automatically. Check the account state before preparing another change."
                ),
            }
            raise HTTPException(502, detail) from None
        # A temporary read failure can be retried once. A 400/401/403 and any
        # write are never automatically replayed.
        if response.status_code in {429, 500, 502, 503, 504} and attempt + 1 < attempts:
            retry_after = str(response.headers.get("Retry-After") or "")
            delay = float(retry_after) if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", retry_after) else 0.5
            # Respect a long Retry-After instead of replaying earlier than
            # Google permits or blocking this interactive request indefinitely.
            if retry_after and (not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", retry_after) or delay > 2):
                break
            time.sleep(delay)
            continue
        break
    try:
        result = response.json()
    except ValueError:
        raise HTTPException(502, {
            "origin": "google_ads_transport", "http_status": 502,
            "message": "Google Ads returned a non-JSON response.",
            "google_request_id": safe_request_id(response.headers.get("request-id")),
            "retryable": read_only, "outcome_unknown": applying_write,
            "next_step": "Inspect the provider response; do not assume a write failed or replay it automatically.",
        }) from None
    failure = decode_google_ads_error(result, response.status_code, response.headers)
    if failure:
        # Log structured diagnostics only. Provider messages/triggers can
        # contain credentials, account data, or user-entered query values.
        logging.getLogger("ads.google_action").warning(
            "google_ads_api_error http_status=%s api_status=%s error_code=%s family=%s request_id=%s field=%s",
            failure["http_status"], failure["api_status"], failure["google_ads_error_code"],
            failure["google_ads_error_family"], failure["google_request_id"], failure["google_ads_error_field"],
        )
        failure["retryable"] = bool(failure["retryable"] and read_only)
        if applying_write and failure["http_status"] >= 500:
            failure["outcome_unknown"] = True
            failure["next_step"] = "Do not replay this mutation automatically. Reconcile the account state using the Google request ID."
        raise HTTPException(failure["http_status"], failure)
    expected = list if path.endswith("/googleAds:searchStream") else dict
    if not isinstance(result, expected):
        raise HTTPException(502, "Google Ads returned an unexpected data format.")
    request_id = safe_request_id(response.headers.get("request-id"))
    if request_id and isinstance(result, dict):
        result = {**result, "requestId": result.get("requestId") or request_id}
    return result


def _read_metadata(method: str, request_ids: list[str] | None = None) -> dict:
    return {
        "source": "Google Ads API", "verified_by_google_api": True,
        "google_api_called": True, "query_method": method,
        "api_version": API_VERSION, "google_request_ids": request_ids or [],
    }


def _read(query: str, tenant_id: str, customer_id: str, manager_id=None, limit: int=100) -> dict:
    rows = []
    next_page = None
    seen_tokens = set()
    request_ids = []
    # Reports fetch one sentinel row beyond the user-visible limit.
    max_rows = min(max(1, int(limit)), MAX_ROWS + 1)
    truncated = False
    for _ in range(4):
        data = {"query": query}
        if next_page:
            data["pageToken"] = next_page
        response = _api(tenant_id, "POST", f"/customers/{customer_id}/googleAds:search", data, manager_id=manager_id)
        if not isinstance(response, dict):
            raise HTTPException(502, "Google Ads Search returned a malformed response.")
        chunk = response.get("results", [])
        if not isinstance(chunk, list) or any(not isinstance(row, dict) for row in chunk):
            raise HTTPException(502, "Google Ads Search returned malformed results.")
        request_id = safe_request_id(response.get("requestId"))
        if request_id and request_id not in request_ids:
            request_ids.append(request_id)
        available = max_rows - len(rows)
        rows.extend(chunk[:available])
        next_page = response.get("nextPageToken")
        if next_page is not None and not isinstance(next_page, str):
            raise HTTPException(502, "Google Ads Search returned a malformed page token.")
        truncated = len(chunk) > available or bool(next_page)
        if not next_page or len(rows) >= max_rows:
            break
        if next_page in seen_tokens:
            raise HTTPException(502, "Google Ads returned a repeated page token; partial results withheld.")
        seen_tokens.add(next_page)
    return {
        "rows": rows, "truncated": truncated, "count": len(rows),
        **_read_metadata("GoogleAdsService.Search", request_ids),
    }


def _read_stream(query: str, tenant_id: str, customer_id: str, manager_id=None, limit: int=100) -> dict:
    """Read all REST response batches and withhold any failed partial stream."""
    batches = _api(
        tenant_id, "POST", f"/customers/{customer_id}/googleAds:searchStream",
        {"query": query}, manager_id=manager_id,
    )
    if not isinstance(batches, list):
        raise HTTPException(502, "Google Ads SearchStream returned an unexpected data format.")
    max_rows = min(max(1, int(limit)), MAX_ROWS + 1)
    rows = []
    total = 0
    request_ids = []
    for batch in batches:
        if not isinstance(batch, dict):
            raise HTTPException(502, "Google Ads SearchStream returned a malformed batch.")
        # The transport normally rejects this; keep the reader safe for other
        # transports and test doubles, too.
        failure = decode_google_ads_error(batch, 200)
        if failure:
            raise HTTPException(failure["http_status"], failure)
        chunk = batch.get("results", [])
        if not isinstance(chunk, list) or any(not isinstance(row, dict) for row in chunk):
            raise HTTPException(502, "Google Ads SearchStream returned malformed results.")
        request_id = safe_request_id(batch.get("requestId"))
        if request_id and request_id not in request_ids:
            request_ids.append(request_id)
        total += len(chunk)
        rows.extend(chunk[:max(0, max_rows - len(rows))])
    return {
        "rows": rows, "count": len(rows), "truncated": total > max_rows,
        **_read_metadata("GoogleAdsService.SearchStream", request_ids),
    }


def _aggregate(rows: list[dict]) -> dict:
    return aggregate_metrics(rows)


def _report(tenant_id: str, args: dict) -> dict:
    plan = prepare_report(args)
    reader = _read_stream if plan["search_stream"] else _read
    result = reader(
        plan["query"], tenant_id, plan["customer_id"], plan["manager_id"], plan["read_limit"],
    )
    return finalize_report(plan, result, api_version=API_VERSION)


def _check_mutations(operations: object, customer_id: str) -> list[dict]:
    if not isinstance(operations, list) or not (1 <= len(operations) <= 50):
        raise HTTPException(422, "Provide 1 to 50 Google Ads mutate operations.")
    for operation in operations:
        if not isinstance(operation, dict) or len(operation) != 1:
            raise HTTPException(422, "Each mutate operation must contain exactly one supported operation type.")
        kind, payload = next(iter(operation.items()))
        if kind not in WRITABLE_OPERATIONS or not isinstance(payload, dict):
            raise HTTPException(422, "Unsupported Google Ads write operation.")
        actions = {"create", "update", "remove"} & set(payload)
        optional = {"updateMask"} if "update" in actions else set()
        if len(actions) != 1 or set(payload) - actions - optional:
            raise HTTPException(422, "Use exactly one of create, update, remove; updates may include updateMask.")
        if "update" in actions and not isinstance(payload.get("updateMask"), str):
            raise HTTPException(422, "Google Ads update operations require an explicit updateMask.")
        obj = payload[next(iter(actions))]
        if ("remove" in actions and not isinstance(obj, str)) or ("remove" not in actions and not isinstance(obj, dict)):
            raise HTTPException(422, "Invalid resource payload.")
        if "update" in actions:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*(?:,[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)*", payload["updateMask"]):
                raise HTTPException(422, "updateMask must list explicit comma-separated field paths.")
            if not isinstance(obj.get("resourceName"), str) or not obj["resourceName"].startswith(f"customers/{customer_id}/"):
                raise HTTPException(422, "An update requires the target customer's resourceName.")
        if "remove" in actions and not obj.startswith(f"customers/{customer_id}/"):
            raise HTTPException(403, "A removal requires the target customer's resourceName.")
        def check_resource(value):
            if isinstance(value, str) and value.startswith("customers/"):
                match = _RESOURCE_RE.match(value)
                if not match or match.group(1) != customer_id:
                    raise HTTPException(403, "Google Ads resource belongs to a different customer.")
            elif isinstance(value, dict):
                for v in value.values():
                    check_resource(v)
            elif isinstance(value, list):
                for v in value:
                    check_resource(v)
        check_resource(obj)
    return operations


def _mutation_response(result: object, operations: list[dict], customer_id: str, *, validate_only: bool = False) -> list:
    """Never report APPLIED for an empty, partial, or mismatched response."""
    if isinstance(result, dict):
        partial = result.get("partialFailureError")
        if isinstance(partial, dict) and partial.get("code", 0) != 0:
            failure = decode_google_ads_error({"error": partial}, 400)
            failure["next_step"] = "Reconcile the account state and failed operation before preparing another change."
            failure["outcome_unknown"] = not validate_only
            raise HTTPException(400, failure)
        if validate_only:
            return []
        responses = result.get("mutateOperationResponses")
        if isinstance(responses, list) and len(responses) == len(operations):
            valid = True
            for operation, response in zip(operations, responses):
                kind, payload = next(iter(operation.items()))
                expected = kind.removesuffix("Operation") + "Result"
                resource = response.get(expected) if isinstance(response, dict) else None
                name = resource.get("resourceName") if isinstance(resource, dict) else None
                if not isinstance(name, str) or not name.startswith(f"customers/{customer_id}/"):
                    valid = False
                    break
                original = payload.get("remove") or (payload.get("update") or {}).get("resourceName")
                if original and name != original:
                    valid = False
                    break
            if valid:
                return responses
    raise HTTPException(502, {
        "origin": "google_ads_response",
        "status": "MUTATION_OUTCOME_UNKNOWN",
        "message": "Google Ads did not return a complete matching mutation result.",
        "outcome_unknown": not validate_only, "retryable": False,
        "next_step": "Do not replay the approved change. Read the affected resources and reconcile the account state first.",
    })


def _prepare_negative_keywords(tenant: str, command: dict) -> dict:
    """Build a scoped, exact-match, validate-only proposal; never write here."""
    allowed = {"action", "customer_id", "manager_id", "campaign_id", "campaign_name",
               "ad_group_id", "keywords", "match_type"}
    extra = set(command) - allowed
    if extra:
        raise HTTPException(422, "Unsupported negative-keyword fields: " + ", ".join(sorted(extra)))
    cid = _customer_id(command.get("customer_id"))
    gid = str(command.get("ad_group_id") or "")
    if not re.fullmatch(r"[1-9][0-9]{0,18}", gid):
        raise HTTPException(422, "Specify the numeric ad_group_id. Never use campaign-level negatives by default.")
    match = str(command.get("match_type") or "EXACT").upper()
    if match != "EXACT":
        raise HTTPException(422, "Bulk negative keyword preview supports EXACT only.")
    supplied = command.get("keywords")
    if not isinstance(supplied, list) or not (1 <= len(supplied) <= 50):
        raise HTTPException(422, "Provide 1 to 50 negative keyword strings.")
    words = []
    seen = set()
    for raw in supplied:
        if not isinstance(raw, str):
            raise HTTPException(422, "Negative keywords must be strings.")
        word = raw.strip()
        if word.startswith("[") and word.endswith("]"):
            word = word[1:-1].strip()
        if not word or len(word) > 80 or any(ord(c) < 32 or ord(c) == 127 for c in word):
            raise HTTPException(422, "Negative keyword must be non-empty, at most 80 characters, and one line.")
        key = word.casefold()
        if key not in seen:
            seen.add(key)
            words.append(word)
    mid = command.get("manager_id")
    if mid:
        mid = _customer_id(mid)

    # Check ad-group ownership and optional campaign scope before proposing any
    # change, rather than trusting a campaign label from the GPT.
    lookup = _read(
        f"SELECT ad_group.id, campaign.id, campaign.name FROM ad_group "
        f"WHERE ad_group.id = {gid} LIMIT 2", tenant, cid, mid, 2
    )
    rows = lookup.get("rows") or []
    if len(rows) != 1:
        raise HTTPException(422, "Ad group was not uniquely found in the requested Google Ads account.")
    group = rows[0].get("adGroup") or rows[0].get("ad_group") or {}
    campaign = rows[0].get("campaign") or {}
    if str(group.get("id")) != gid:
        raise HTTPException(422, "Google Ads did not confirm the requested ad group ID.")
    if command.get("campaign_id") and str(campaign.get("id")) != str(command["campaign_id"]):
        raise HTTPException(422, "The ad group belongs to a different campaign ID.")
    if command.get("campaign_name") and campaign.get("name") != command["campaign_name"]:
        raise HTTPException(422, "The ad group belongs to a different campaign name.")

    # Existing exact negatives are not created twice.
    existing_result = _read(
        "SELECT ad_group_criterion.keyword.text, ad_group_criterion.keyword.match_type "
        "FROM ad_group_criterion WHERE "
        f"ad_group.id = {gid} AND ad_group_criterion.negative = TRUE "
        "AND ad_group_criterion.type = KEYWORD",
        tenant, cid, mid, 300
    )
    if existing_result.get("truncated"):
        raise HTTPException(409, "Existing negative-keyword inventory is incomplete. Review it before adding more.")
    existing = set()
    for item in existing_result.get("rows") or []:
        criterion = item.get("adGroupCriterion") or item.get("ad_group_criterion") or {}
        kw = criterion.get("keyword") or {}
        if kw.get("matchType", kw.get("match_type")) == "EXACT":
            existing.add(str(kw.get("text") or "").strip().casefold())
    already_present = [w for w in words if w.casefold() in existing]
    to_add = [w for w in words if w.casefold() not in existing]
    if not to_add:
        return {"ok": True, "provider": "google_ads", "status": "NO_CHANGES_NEEDED",
                "customer_id": cid, "ad_group_id": gid, "already_present": already_present,
                "no_changes_applied": True}
    operations = [{
        "adGroupCriterionOperation": {"create": {
            "adGroup": f"customers/{cid}/adGroups/{gid}",
            "negative": True,
            "keyword": {"text": word, "matchType": "EXACT"},
        }}
    } for word in to_add]
    preview = execute_google_ads_command({
        "action": "prepare_mutation", "customer_id": cid, "manager_id": mid,
        "operations": operations,
    }, {"tenant_id": tenant})
    return {**preview, "ad_group_id": gid, "match_type": "EXACT",
            "new_keywords": to_add, "already_present": already_present,
            "no_changes_applied": True}


def execute_google_ads_command(command: dict, identity: dict) -> dict:
    tenant = identity["tenant_id"]
    action = str(command.get("action") or "list_accounts").lower()
    if action == "ping":
        return {
            "ok": True,
            "provider": "google_ads",
            "action": "ping",
            "intent_reached": True,
            "google_api_called": False,
            "message": "The existing GPT Action successfully called /tools/intent and executed the Google Ads handler.",
            "next_step": "Now send google_ads list_accounts to verify the live Google Ads API.",
        }
    if action == "status":
        existing = get_active_google_connection_for_tenant(tenant)
        connected = bool(existing and existing.get("connection_mode") == "oauth" and ADS_SCOPE in str(existing.get("scopes") or "").split())
        # OAuth consent by itself does NOT prove Google Ads API access.
        # Run an actual read request so GPT doesn't stop at a capability list.
        answer = {"ok": True, "provider": "google_ads", "connected": connected,
                  "oauth_scope_connected": connected,
                  "google_ads_api_ok": False,
                  "connect_url": None if connected else _connect_url(tenant),
                  "available_actions": ["ping", "list_accounts", "inspect_campaign", "audit_crm_migration", "clone_campaign", "report", "query", "keyword_inventory", "prepare_mutation", "commit_mutation"],
                  "reports": list(REPORTS),
                  "next_step": "If Google Ads API access is valid, use list_accounts or inspect_campaign in this same /tools/intent action; these commands execute live reads."}
        if connected:
            try:
                live = _api(tenant, "GET", "/customers:listAccessibleCustomers")
                answer["google_ads_api_ok"] = True
                answer["accounts"] = live.get("resourceNames") or []
                answer["verified_account_ids"] = [r.split("/")[-1] for r in answer["accounts"] if re.fullmatch(r"customers/[0-9]{10}", r)]
            except HTTPException as exc:
                answer["read_error_http_status"] = exc.status_code
                answer["read_error"] = exc.detail
                answer["next_step"] = "Fix the Google Ads API read error shown above. OAuth scope by itself does not prove working Ads access."
        return answer
    if action == "list_accounts":
        from app.core.google_ads_discovery import list_accounts_live
        return {"ok": True, **list_accounts_live(tenant, expand_clients=True)}
    if action in {"inspect_campaign", "discover_campaign"}:
        from app.core.google_ads_discovery import inspect_campaign_live
        return {"ok": True, **inspect_campaign_live(
            tenant,
            command.get("campaign_name"),
            customer_id=command.get("customer_id"),
            manager_id=command.get("manager_id"),
            date_range=str(command.get("date_range") or "LAST_7_DAYS").upper(),
            date=command.get("date"), start_date=command.get("start_date"),
            end_date=command.get("end_date"), campaign_id=command.get("campaign_id"),
        )}
    if action == "audit_crm_migration":
        from app.core.google_ads_migration_audit import audit_crm_migration
        return audit_crm_migration(
            tenant=tenant,
            customer_id=command.get("customer_id"),
            campaign_id=command.get("campaign_id"),
            ad_group_id=command.get("ad_group_id"),
            manager_id=command.get("manager_id"),
        )
    if action in {"clone_campaign", "duplicate_campaign"}:
        from app.core.google_ads_clone import preview_clone_campaign
        return preview_clone_campaign(tenant, command)
    if action == "keyword_inventory":
        from app.core.google_ads_keyword_inventory import read_keyword_inventory
        return read_keyword_inventory(tenant, command)
    if action in {"report", "analysis"}:
        result = _report(tenant, command)
        return {"ok": True, "provider": "google_ads", **result}
    if action == "query":
        customer_id = _customer_id(command.get("customer_id"))
        plan = prepare_query(command)
        manager_id = command.get("manager_id") or command.get("login_customer_id")
        if command.get("manager_id") and command.get("login_customer_id") and _customer_id(command["manager_id"]) != _customer_id(command["login_customer_id"]):
            raise HTTPException(422, "manager_id and login_customer_id disagree.")
        if manager_id:
            manager_id = _customer_id(manager_id)
        result = (_read_stream if plan["search_stream"] else _read)(
            plan["query"], tenant, customer_id, manager_id, plan["read_limit"])
        return {"ok": True, "provider": "google_ads", "customer_id": customer_id,
                **finalize_query(plan, result)}
    if action == "prepare_negative_keywords":
        return _prepare_negative_keywords(tenant, command)
    if action == "prepare_mutation":
        cid = _customer_id(command.get("customer_id"))
        ops = _check_mutations(command.get("operations"), cid)
        mid = command.get("manager_id")
        if mid:
            _customer_id(mid)
        # Validate with Google Ads before issuing an approval token; no changes applied.
        validation = _api(tenant, "POST", f"/customers/{cid}/googleAds:mutate",
                          {"mutateOperations": ops, "validateOnly": True, "partialFailure": False},
                          manager_id=mid)
        _mutation_response(validation, ops, cid, validate_only=True)
        approval_code = create_auth_code(tenant, "google_ads_mutation_approval", expires_in=600)
        approval_token = _signer("google-ads-mut-v1").dumps({
            "tenant_id": tenant, "customer_id": cid, "manager_id": mid,
            "operations": ops, "approval_code": approval_code,
        })
        return {
            "ok": True, "status": "AWAITING_USER_CONFIRMATION",
            "message": "Validated by Google Ads; no changes have been applied.",
            "customer_id": cid, "operations": ops,
            "approval_token": approval_token,
            "next_step": "Explain every change and obtain explicit user approval. Then call commit_mutation with approval_token and confirmation_phrase.",
            "confirmation_phrase": "CONFIRM_GOOGLE_ADS_CHANGE",
        }
    if action == "commit_mutation":
        if command.get("confirmation_phrase") != "CONFIRM_GOOGLE_ADS_CHANGE":
            raise HTTPException(403, "Explicit approval phrase is required.")
        token = str(command.get("approval_token") or "")
        try:
            details = _signer("google-ads-mut-v1").loads(token, max_age=600)
        except (BadSignature, SignatureExpired):
            raise HTTPException(403, "Approval expired. Preview the change again.")
        if details.get("tenant_id") != tenant:
            raise HTTPException(403, "Approval belongs to a different tenant.")
        cid = _customer_id(details["customer_id"])
        operations = _check_mutations(details.get("operations"), cid)
        if command.get("customer_id") is not None and _customer_id(command["customer_id"]) != cid:
            raise HTTPException(403, "The customer differs from the approved preview.")
        if command.get("operations") is not None and command["operations"] != operations:
            raise HTTPException(403, "The operations differ from the approved preview.")
        if command.get("manager_id") is not None and command["manager_id"] != details.get("manager_id"):
            raise HTTPException(403, "The manager differs from the approved preview.")
        code = str(details.get("approval_code") or "")
        approved_once = consume_auth_code(code)
        if not approved_once or approved_once.get("tenant_id") != tenant or approved_once.get("meta_user_id") != "google_ads_mutation_approval":
            raise HTTPException(409, "Approval already used, expired, or invalid.")
        result = _api(tenant, "POST", f"/customers/{cid}/googleAds:mutate",
                      {"mutateOperations": operations, "partialFailure": False, "validateOnly": False},
                      manager_id=details.get("manager_id"))
        responses = _mutation_response(result, operations, cid)
        return {"ok": True, "status": "APPLIED", "provider": "google_ads", "customer_id": cid,
                "verified_by_google_api": True, "google_api_called": True,
                "google_request_id": safe_request_id(result.get("requestId")),
                "results": responses}
    raise HTTPException(422, "Unknown Google Ads action.")


def _detect(command: str) -> bool:
    from app.core.google_ads_intent import detect_google_ads_request
    return detect_google_ads_request(command)


def parse_google_ads_request(body) -> dict:
    from app.core.google_ads_intent import parse_google_ads_request as parse
    return parse(body)


async def google_ads_intent(body, request: Request) -> dict:
    identity = _required_app_identity(request)
    supplied_tenant = str(body.tenant_id or "").strip()
    if supplied_tenant and supplied_tenant != identity["tenant_id"]:
        raise HTTPException(403, "Tenant identity does not match the connected GPT.")
    command = parse_google_ads_request(body)
    try:
        return execute_google_ads_command(command, identity)
    except HTTPException as exc:
        # ChatGPT Actions may swallow tool-level HTTP failures and never print
        # their details. For READS only, return a small 200 JSON diagnostic.
        # Auth failure above and all write actions retain their error codes.
        read_actions = {"status", "list_accounts", "inspect_campaign", "discover_campaign", "audit_crm_migration", "clone_campaign", "duplicate_campaign", "report", "analysis", "query", "keyword_inventory"}
        action = str(command.get("action") or "").lower()
        if action not in read_actions:
            raise
        detail = exc.detail
        if isinstance(detail, dict):
            safe = {
                key: detail.get(key)
                for key in ("origin", "http_status", "api_status", "google_ads_error_code", "google_ads_error_category", "google_ads_error_family", "google_ads_error_field", "google_ads_errors", "google_request_id", "retryable",
                            "message", "next_step", "connect_url", "required_scope")
                if key in detail
            }
        else:
            safe = {"message": str(detail)[:180]}
        return {
            "ok": False,
            "provider": "google_ads",
            "action": action,
            "status": "READ_FAILED",
            "http_status": exc.status_code,
            "google_api_called": safe.get("origin") in {"google_ads_api", "google_ads_official_sdk", "google_ads_response"},
            "error": safe,
            "message": "Google Ads read was rejected; no advertising changes were made.",
            "next_step": safe.get("next_step") or "Review the structured error and resolve the Google OAuth or API access issue.",
        }
