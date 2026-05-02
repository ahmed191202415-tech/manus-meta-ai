from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException

from app.config import DEFAULT_PAGE_LIMIT, DEFAULT_MAX_PAGES
from app.core.auth import resolve_access_token
from app.core.pagination import meta_get_all_pages
from app.core.meta_client import meta_call, normalize_account_id
from app.analytics.preprocessing import DEFAULT_INSIGHTS_FIELDS

router = APIRouter(tags=["insights"])

SAFE_INSIGHTS_FIELDS = "account_id,account_name,campaign_id,campaign_name,adset_id,adset_name,ad_id,ad_name,objective,spend,reach,frequency,impressions,inline_link_clicks,ctr,cpc,cpm,actions,cost_per_action_type,date_start,date_stop"


def _is_params_error(exc: HTTPException) -> bool:
    detail = exc.detail
    msg = str(detail).lower()
    return exc.status_code in {400, 403} and any(x in msg for x in [
        "field", "fields", "param", "parameter", "time_range", "filtering", "breakdown", "permission", "unsupported", "invalid",
    ])


def _safe_params(params: Dict[str, Any]) -> Dict[str, Any]:
    safe = {
        "level": params.get("level") or "campaign",
        "fields": SAFE_INSIGHTS_FIELDS,
        "limit": min(int(params.get("limit") or 100), 100),
    }
    # Keep one valid date selector only. Prefer explicit time_range, otherwise date_preset.
    if params.get("time_range"):
        safe["time_range"] = params["time_range"]
    elif params.get("date_preset"):
        safe["date_preset"] = params["date_preset"]
    else:
        safe["date_preset"] = "last_30d"
    if params.get("filtering"):
        safe["filtering"] = params["filtering"]
    if params.get("after"):
        safe["after"] = params["after"]
    return safe


@router.get("/insights")
async def get_insights(
    account_id: str,
    level: str = "campaign",
    date_preset: Optional[str] = "last_30d",
    time_range: Optional[str] = None,
    time_increment: Optional[str] = None,
    breakdowns: Optional[str] = None,
    action_breakdowns: Optional[str] = None,
    filtering: Optional[str] = None,
    sort: Optional[str] = None,
    fields: str = DEFAULT_INSIGHTS_FIELDS,
    limit: int = DEFAULT_PAGE_LIMIT,
    after: Optional[str] = None,
    fetch_all: bool = False,
    max_pages: int = DEFAULT_MAX_PAGES,
    token: str = Depends(resolve_access_token),
):
    account_id = normalize_account_id(account_id)

    params: Dict[str, Any] = {
        "level": level,
        "fields": fields,
        "limit": limit,
    }

    if date_preset:
        params["date_preset"] = date_preset
    if time_range:
        params["time_range"] = time_range
    if time_increment:
        params["time_increment"] = time_increment
    if breakdowns:
        params["breakdowns"] = breakdowns
    if action_breakdowns:
        params["action_breakdowns"] = action_breakdowns
    if filtering:
        params["filtering"] = filtering
    if sort:
        params["sort"] = sort
    if after:
        params["after"] = after

    try:
        if fetch_all:
            return meta_get_all_pages(f"{account_id}/insights", token, params=params, max_pages=max_pages)
        return meta_call("GET", f"{account_id}/insights", token, params=params)
    except HTTPException as exc:
        if not _is_params_error(exc):
            raise
        fallback_params = _safe_params(params)
        try:
            if fetch_all:
                result = meta_get_all_pages(f"{account_id}/insights", token, params=fallback_params, max_pages=max_pages)
            else:
                result = meta_call("GET", f"{account_id}/insights", token, params=fallback_params)
            if isinstance(result, dict):
                result["_fallback"] = {
                    "reason": "Meta rejected the original insights params; retried with safe fields/params.",
                    "original_error": exc.detail,
                    "used_params": fallback_params,
                }
            return result
        except HTTPException:
            raise exc
