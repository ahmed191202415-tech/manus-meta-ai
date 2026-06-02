from fastapi import APIRouter, Depends, HTTPException

from app.schemas.meta_requests import RawMetaRequest, ReadOnlyMetaQueryRequest, SmartMetaInsightsRequest
from app.core.auth import resolve_access_token
from app.core.meta_client import meta_call
from app.core.token_router import choose_token_for_meta_path

router = APIRouter(prefix="/meta", tags=["meta"])
SMART_INSIGHTS_FIELDS = (
    "account_id,account_name,campaign_id,campaign_name,adset_id,adset_name,ad_id,ad_name,"
    "objective,spend,impressions,reach,frequency,clicks,inline_link_clicks,outbound_clicks,"
    "actions,cost_per_action_type,cpc,cpm,ctr,date_start,date_stop"
)
MINIMAL_SMART_INSIGHTS_FIELDS = (
    "account_id,account_name,campaign_id,campaign_name,adset_id,adset_name,ad_id,ad_name,"
    "spend,impressions,reach,inline_link_clicks,outbound_clicks,actions,date_start,date_stop"
)


def _clean(value) -> str:
    return str(value or "").strip()


def _normalized_account_id(value) -> str:
    clean_value = _clean(value)
    if clean_value and not clean_value.startswith("act_"):
        return f"act_{clean_value}"
    return clean_value


def _available_ad_accounts(token: str) -> list[dict]:
    payload = meta_call(
        "GET",
        "me/adaccounts",
        token,
        params={"fields": "id,name,account_id,account_status,currency,timezone_name", "limit": 200},
    )
    return payload.get("data", [])


def _resolve_ad_account(body: SmartMetaInsightsRequest, token: str) -> tuple[str | None, list[dict]]:
    clean_account_id = _normalized_account_id(body.account_id)
    if clean_account_id:
        return clean_account_id, []
    accounts = _available_ad_accounts(token)
    clean_name = _clean(body.account_name).casefold()
    if clean_name:
        matches = [item for item in accounts if clean_name in _clean(item.get("name")).casefold()]
        if len(matches) == 1:
            return _normalized_account_id(matches[0].get("id") or matches[0].get("account_id")), accounts
    if len(accounts) == 1:
        return _normalized_account_id(accounts[0].get("id") or accounts[0].get("account_id")), accounts
    return None, accounts


def _smart_scope(body: SmartMetaInsightsRequest, account_id: str) -> tuple[str, str, str]:
    if body.ad_id:
        return _clean(body.ad_id), "ad", "ad"
    if body.adset_id:
        return _clean(body.adset_id), "adset", "adset"
    if body.campaign_id:
        return _clean(body.campaign_id), "campaign", "campaign"
    return account_id, body.level or "campaign", "account"


def _smart_date_params(body: SmartMetaInsightsRequest) -> dict:
    if body.since and body.until:
        return {"time_range": {"since": body.since, "until": body.until}}
    return {"date_preset": body.date_preset or "last_7d"}


def _safe_meta_read(path: str, token: str, params: dict) -> tuple[dict | None, dict | None]:
    try:
        return meta_call("GET", path, token, params=params), None
    except HTTPException as exc:
        return None, {"path": path, "error": exc.detail}


@router.post("/smart_insights")
async def smart_meta_insights(body: SmartMetaInsightsRequest, token: str = Depends(resolve_access_token)):
    account_id, available_accounts = _resolve_ad_account(body, token)
    if not account_id:
        return {
            "ok": False,
            "needs_account_selection": True,
            "message": "Select one Meta ad account by account_id or provide a more specific account_name.",
            "available_accounts": available_accounts,
        }
    scope_id, level, scope_type = _smart_scope(body, account_id)
    path = f"{scope_id}/insights"
    params = {
        "fields": SMART_INSIGHTS_FIELDS,
        "level": level,
        "limit": body.limit,
        **_smart_date_params(body),
    }
    if body.time_increment:
        params["time_increment"] = body.time_increment
    if body.breakdowns:
        params["breakdowns"] = body.breakdowns
    insights, primary_error = _safe_meta_read(path, token, params)
    warnings = []
    fields_mode = "standard"
    if insights is None:
        fields_mode = "minimal_fallback"
        warnings.append({"type": "standard_fields_rejected", "details": primary_error})
        insights, minimal_error = _safe_meta_read(path, token, {**params, "fields": MINIMAL_SMART_INSIGHTS_FIELDS})
        if insights is None:
            return {
                "ok": False,
                "source": "meta_insights",
                "scope": {"type": scope_type, "id": scope_id, "level": level, "account_id": account_id},
                "path": path,
                "warnings": warnings,
                "error": minimal_error,
                "message": "Meta rejected both standard and minimal direct insights requests.",
            }
    context = None
    if scope_type != "account":
        context, context_error = _safe_meta_read(
            scope_id,
            token,
            {"fields": "id,name,status,effective_status,objective,created_time,updated_time"},
        )
        if context_error:
            warnings.append({"type": "entity_context_unavailable", "details": context_error})
    return {
        "ok": True,
        "source": "meta_insights",
        "scope": {"type": scope_type, "id": scope_id, "level": level, "account_id": account_id},
        "path": path,
        "fields_mode": fields_mode,
        "entity_context": context,
        "insights": insights,
        "warnings": warnings,
        "permission_note": (
            "A separate Pixel or Events Manager permission failure does not invalidate these campaign, ad set, or ad insights."
        ),
    }


@router.post(
    "/query",
    summary="Dynamic Meta Graph read",
    description=(
        "Primary Meta tool for natural-language user questions. Build the Meta Graph path and focused GET params "
        "from the user's request, then read Meta directly. Use discovery paths such as me/adaccounts, "
        "act_<ACCOUNT_ID>/campaigns, <CAMPAIGN_ID>/adsets, or <ADSET_ID>/ads when IDs are unknown. For performance "
        "data, prefer direct <CAMPAIGN_ID>/insights, <ADSET_ID>/insights, or <AD_ID>/insights paths once the entity "
        "is known. This tool is read-only."
    ),
)
async def read_only_meta_query(body: ReadOnlyMetaQueryRequest, token: str = Depends(resolve_access_token)):
    effective_token = choose_token_for_meta_path(
        user_token=token,
        path=body.path,
        method="GET",
        params=body.params,
    )
    try:
        return {
            "ok": True,
            "path": body.path,
            "data": meta_call("GET", body.path, effective_token, params=body.params),
        }
    except HTTPException as exc:
        return {
            "ok": False,
            "path": body.path,
            "error": exc.detail,
            "next_step": (
                "Inspect this Meta Graph error. If the path is an insights edge, retry only after correcting "
                "the rejected token, permission, field, or parameter. Do not repeat the same request unchanged."
            ),
        }


@router.post(
    "/request",
    summary="Dynamic Meta Graph write",
    description=(
        "Meta Graph write tool for explicit user commands only. Use it to create, edit, publish, pause, resume, "
        "delete, or reply through Meta after confirming the intended write action with the user. Do not use this "
        "tool for analysis or discovery reads; use /meta/query for those."
    ),
)
async def raw_meta_request(body: RawMetaRequest, token: str = Depends(resolve_access_token)):
    effective_token = choose_token_for_meta_path(
        user_token=token,
        path=body.path,
        method=body.method,
        params=body.params,
        data=body.data,
    )
    return meta_call(body.method, body.path, effective_token, params=body.params, data=body.data)
