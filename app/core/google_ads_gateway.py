"""Google Ads API v25 gateway for existing GPT Actions (no schema change).

Uses the existing per-tenant Google OAuth connection. Never accepts an access
token, refresh token or tenant identity from natural-language GPT inputs.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import json
import os
import re
import secrets
from urllib.parse import quote

import requests
from fastapi import HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import PUBLIC_BASE_URL, SESSION_SECRET
from app.core.ga4_client import get_google_credentials_for_tenant
from app.core.oauth_store import (
    consume_auth_code, create_auth_code, get_active_google_connection_for_tenant,
    get_app_token_data,
)

BASE = "https://googleads.googleapis.com/v25"
ADS_SCOPE = "https://www.googleapis.com/auth/adwords"
MAX_ROWS = 300
DURATIONS = {"TODAY", "YESTERDAY", "LAST_7_DAYS", "LAST_14_DAYS", "LAST_30_DAYS", "THIS_MONTH", "LAST_MONTH", "ALL_TIME"}
REPORTS = {
    "campaigns": (
        "campaign.id, campaign.name, campaign.status, campaign.advertising_channel_type,"
        " campaign.campaign_budget, metrics.cost_micros, metrics.impressions, metrics.clicks,"
        " metrics.conversions, metrics.conversions_value, metrics.ctr, metrics.average_cpc"
    , "campaign"),
    "ad_groups": (
        "campaign.id, campaign.name, ad_group.id, ad_group.name, ad_group.status,"
        " metrics.cost_micros, metrics.impressions, metrics.clicks, metrics.conversions,"
        " metrics.conversions_value, metrics.ctr, metrics.average_cpc"
    , "ad_group"),
    "ads": (
        "campaign.name, ad_group.name, ad_group_ad.ad.id, ad_group_ad.ad.name,"
        " ad_group_ad.status, metrics.cost_micros, metrics.impressions, metrics.clicks,"
        " metrics.conversions, metrics.ctr"
    , "ad_group_ad"),
    "keywords": (
        "campaign.name, ad_group.name, ad_group_criterion.criterion_id,"
        " ad_group_criterion.keyword.text, ad_group_criterion.keyword.match_type,"
        " ad_group_criterion.status, ad_group_criterion.quality_info.quality_score,"
        " metrics.cost_micros, metrics.impressions, metrics.clicks, metrics.conversions,"
        " metrics.ctr, metrics.average_cpc"
    , "keyword_view"),
    "search_terms": (
        "search_term_view.search_term, campaign.name, ad_group.name,"
        " metrics.cost_micros, metrics.impressions, metrics.clicks, metrics.conversions,"
        " metrics.ctr, metrics.average_cpc"
    , "search_term_view"),
    "budgets": (
        "campaign_budget.id, campaign_budget.name, campaign_budget.amount_micros,"
        " campaign_budget.status, campaign_budget.delivery_method"
    , "campaign_budget"),
    "daily": (
        "segments.date, campaign.name, metrics.cost_micros, metrics.impressions,"
        " metrics.clicks, metrics.conversions, metrics.conversions_value"
    , "campaign"),
    "devices": (
        "segments.device, campaign.name, metrics.cost_micros, metrics.impressions,"
        " metrics.clicks, metrics.conversions, metrics.ctr"
    , "campaign"),
    "conversions": (
        "conversion_action.id, conversion_action.name, conversion_action.type,"
        " conversion_action.status, conversion_action.category"
    , "conversion_action"),
    "negative_keywords": (
        "campaign.name, ad_group.name, ad_group_criterion.keyword.text,"
        " ad_group_criterion.keyword.match_type, ad_group_criterion.negative"
    , "ad_group_criterion"),
}
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
        identity = None
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


def _api(tenant_id: str, method: str, path: str, body: dict | None = None, *, manager_id=None) -> dict:
    credentials = _credentials(tenant_id)
    try:
        response = requests.request(
            method, BASE + path, headers=_headers(credentials, manager_id),
            json=body, timeout=45,
        )
    except requests.RequestException:
        raise HTTPException(502, "Google Ads API could not be reached.")
    try:
        result = response.json()
    except ValueError:
        raise HTTPException(502, "Google Ads returned a non-JSON response.")
    if response.status_code >= 400:
        err = (result.get("error") or {}) if isinstance(result, dict) else {}
        # Do not expose account credentials, request headers, or Google raw traces.
        raise HTTPException(response.status_code, {
            "message": str(err.get("message") or "Google Ads API request failed.")[:450],
            "status": str(err.get("status") or "")[:100],
            "hint": "Check Google Cloud Ads API access, OAuth permissions, customer ID, and manager account." ,
        })
    if not isinstance(result, dict):
        raise HTTPException(502, "Google Ads returned an unexpected data format.")
    return result


def _read(query: str, tenant_id: str, customer_id: str, manager_id=None, limit: int=100) -> dict:
    rows = []
    next_page = None
    max_rows = min(max(1, int(limit)), MAX_ROWS)
    for _ in range(4):
        data = {"query": query}
        if next_page:
            data["pageToken"] = next_page
        response = _api(tenant_id, "POST", f"/customers/{customer_id}/googleAds:search", data, manager_id=manager_id)
        rows.extend(response.get("results") or [])
        next_page = response.get("nextPageToken")
        if not next_page or len(rows) >= max_rows:
            break
    return {"rows": rows[:max_rows], "truncated": bool(next_page) or len(rows)>max_rows, "count": min(len(rows), max_rows)}


def _aggregate(rows: list[dict]) -> dict:
    spend_micro = 0
    clicks = 0
    impressions = 0
    conversions = Decimal(0)
    value = Decimal(0)
    for row in rows:
        m = row.get("metrics") or {}
        try:
            spend_micro += int(m.get("costMicros") or 0)
            clicks += int(m.get("clicks") or 0)
            impressions += int(m.get("impressions") or 0)
            conversions += Decimal(str(m.get("conversions") or "0"))
            value += Decimal(str(m.get("conversionsValue") or "0"))
        except (ValueError, InvalidOperation, TypeError):
            continue
    spend = Decimal(spend_micro) / Decimal(1000000)
    return {
        "cost": str(spend), "clicks": clicks, "impressions": impressions,
        "conversions": str(conversions), "conversion_value": str(value),
        "ctr_percent": round(clicks * 100 / impressions, 3) if impressions else None,
        "cpc": str(round(spend / clicks, 2)) if clicks else None,
        "cost_per_conversion": str(round(spend / conversions, 2)) if conversions else None,
        "roas": str(round(value / spend, 2)) if spend else None,
        "note": "Cost is in the selected account currency. Conversions reflect Google Ads attribution, not verified CRM sales.",
    }


def _report(tenant_id: str, args: dict) -> dict:
    customer_id = _customer_id(args.get("customer_id"))
    report = str(args.get("report") or "campaigns").lower()
    if report not in REPORTS:
        raise HTTPException(422, "Unknown report. Use: " + ", ".join(REPORTS))
    duration = str(args.get("date_range") or "LAST_7_DAYS").upper()
    if duration not in DURATIONS:
        raise HTTPException(422, "Unsupported Google Ads date range.")
    fields, resource = REPORTS[report]
    query = f"SELECT {fields} FROM {resource}"
    if report not in {"budgets", "conversions", "negative_keywords"} and duration != "ALL_TIME":
        query += f" WHERE segments.date DURING {duration}"
    if report == "negative_keywords":
        query += " WHERE ad_group_criterion.negative = TRUE"
    query += f" LIMIT {min(max(int(args.get('limit') or 100), 1), MAX_ROWS)}"
    res = _read(query, tenant_id, customer_id, args.get("manager_id"), args.get("limit") or 100)
    res.update({"customer_id": customer_id, "report": report, "date_range": duration})
    if report in {"campaigns", "ad_groups", "ads", "keywords", "search_terms", "daily", "devices"}:
        res["summary"] = _aggregate(res["rows"])
    return res


def _check_mutations(operations: object, customer_id: str) -> list[dict]:
    if not isinstance(operations, list) or not (1 <= len(operations) <= 20):
        raise HTTPException(422, "Provide 1 to 20 Google Ads mutate operations.")
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
        if not isinstance(obj, (dict, str)):
            raise HTTPException(422, "Invalid resource payload.")
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


def execute_google_ads_command(command: dict, identity: dict) -> dict:
    tenant = identity["tenant_id"]
    action = str(command.get("action") or "list_accounts").lower()
    if action == "status":
        existing = get_active_google_connection_for_tenant(tenant)
        connected = bool(existing and existing.get("connection_mode") == "oauth" and ADS_SCOPE in str(existing.get("scopes") or "").split())
        # OAuth consent by itself does NOT prove Google Ads API access.
        # Run an actual read request so GPT doesn't stop at a capability list.
        answer = {"ok": True, "provider": "google_ads", "connected": connected,
                  "oauth_scope_connected": connected,
                  "google_ads_api_ok": False,
                  "connect_url": None if connected else _connect_url(tenant),
                  "available_actions": ["list_accounts", "inspect_campaign", "report", "query", "prepare_mutation", "commit_mutation"],
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
        )}
    if action in {"report", "analysis"}:
        result = _report(tenant, command)
        return {"ok": True, "provider": "google_ads", **result}
    if action == "query":
        customer_id = _customer_id(command.get("customer_id"))
        query = str(command.get("query") or "").strip()
        if not re.match(r"(?is)^SELECT\s+", query) or len(query)>6000 or ";" in query or "--" in query or "/*" in query:
            raise HTTPException(422, "Only a single read-only GAQL SELECT statement is supported.")
        return {"ok": True, "provider": "google_ads", "customer_id": customer_id,
                **_read(query, tenant, customer_id, command.get("manager_id"), command.get("limit") or 100)}
    if action == "prepare_mutation":
        cid = _customer_id(command.get("customer_id"))
        ops = _check_mutations(command.get("operations"), cid)
        mid = command.get("manager_id")
        if mid:
            _customer_id(mid)
        # Validate with Google Ads before issuing an approval token; no changes applied.
        _api(tenant, "POST", f"/customers/{cid}/googleAds:mutate",
             {"mutateOperations": ops, "validateOnly": True, "partialFailure": False},
             manager_id=mid)
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
        code = str(details.get("approval_code") or "")
        approved_once = consume_auth_code(code)
        if not approved_once or approved_once.get("tenant_id") != tenant or approved_once.get("meta_user_id") != "google_ads_mutation_approval":
            raise HTTPException(409, "Approval already used, expired, or invalid.")
        result = _api(tenant, "POST", f"/customers/{cid}/googleAds:mutate",
                      {"mutateOperations": operations, "partialFailure": False, "validateOnly": False},
                      manager_id=details.get("manager_id"))
        return {"ok": True, "status": "APPLIED", "provider": "google_ads", "customer_id": cid,
                "results": result.get("mutateOperationResponses") or result}
    raise HTTPException(422, "Unknown Google Ads action.")


def _detect(command: str) -> bool:
    value = command.lower()
    return any(x in value for x in ("google_ads", "google ads", "google adwords", "adwords", "جوجل ادز", "جوجل أدز", "اعلانات جوجل", "إعلانات جوجل", "google search ads")) or ("جوجل" in value and any(w in value for w in ("اعلان", "إعلان", "حمل", "ads", "كلمات البحث")))


def parse_google_ads_request(body) -> dict:
    message = str(body.request or "").strip()
    start = message.find("{")
    if start != -1 and _detect(message[:start]):
        try:
            data = json.loads(message[start:])
        except json.JSONDecodeError:
            raise HTTPException(422, "Send one valid JSON command after 'google_ads'.")
        if not isinstance(data, dict):
            raise HTTPException(422, "Google Ads command must be a JSON object.")
        return data
    lower = message.lower()
    if any(x in lower for x in ("ربط", "connect", "حاله الاتصال", "الحالة", "status")):
        return {"action": "status"}
    # Natural user requests can inspect named campaigns in ONE authorized
    # server call, including all available account IDs and ad groups.
    campaign_name = str(getattr(body, "campaign_name", "") or "").strip()
    if not campaign_name:
        match_name = re.search(r"(?<![a-zA-Z0-9])(?:[a-zA-Z][a-zA-Z0-9]*-){1,}[a-zA-Z0-9]+(?![a-zA-Z0-9])", message)
        if match_name:
            campaign_name = match_name.group(0)
    if campaign_name:
        match_id = re.search(r"(?<!\\d)(?:[0-9]{3}-[0-9]{3}-[0-9]{4}|[0-9]{10})(?!\\d)", message)
        return {
            "action": "inspect_campaign",
            "campaign_name": campaign_name,
            "customer_id": match_id.group(0) if match_id else None,
            "date_range": "TODAY" if any(x in lower for x in ("today", "النهارده", "اليوم")) else "LAST_7_DAYS",
        }
    if any(x in lower for x in ("حساب", "account", "account list")):
        return {"action": "list_accounts"}
    report = "campaigns"
    for words, kind in [
        (("search term", "عبارات البحث", "مصطلحات البحث"), "search_terms"),
        (("keyword", "الكلمات", "كلمات البحث"), "keywords"),
        (("ad group", "مجموعات", "المجموعات"), "ad_groups"),
        (("budget", "الميزانيات"), "budgets"),
        (("conversion", "تحويلات"), "conversions"),
        (("devices", "الأجهزة"), "devices"),
    ]:
        if any(w in lower for w in words):
            report = kind
            break
    duration = "LAST_7_DAYS"
    if any(x in lower for x in ("today", "النهارده", "اليوم")):
        duration = "TODAY"
    elif any(x in lower for x in ("yesterday", "امبارح", "أمس")):
        duration = "YESTERDAY"
    elif any(x in lower for x in ("last 30", "آخر 30", "شهر")):
        duration = "LAST_30_DAYS"
    cid = body.meta_account_id
    match = re.search(r"(?<!\d)(?:[0-9]{3}-[0-9]{3}-[0-9]{4}|[0-9]{10})(?!\d)", message)
    if match:
        cid = match.group(0)
    if not cid:
        return {"action": "list_accounts", "note": "Choose a Google Ads customer_id from these accounts, then request a report."}
    return {"action": "report", "customer_id": cid, "report": report, "date_range": duration}


async def google_ads_intent(body, request: Request) -> dict:
    identity = _required_app_identity(request)
    supplied_tenant = str(body.tenant_id or "").strip()
    if supplied_tenant and supplied_tenant != identity["tenant_id"]:
        raise HTTPException(403, "Tenant identity does not match the connected GPT.")
    command = parse_google_ads_request(body)
    return execute_google_ads_command(command, identity)
