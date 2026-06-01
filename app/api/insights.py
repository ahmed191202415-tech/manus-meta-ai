import json
from typing import Optional, Dict, Any

from fastapi import APIRouter, Depends

from app.config import DEFAULT_PAGE_LIMIT, DEFAULT_MAX_PAGES
from app.core.auth import resolve_access_token
from app.core.meta_client import normalize_account_id
from app.analytics.preprocessing import DEFAULT_INSIGHTS_FIELDS, fetch_insights_payload

router = APIRouter(tags=["insights"])


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
    campaign_id: Optional[str] = None,
    campaign_name: Optional[str] = None,
    adset_id: Optional[str] = None,
    ad_id: Optional[str] = None,
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
    filters = _build_insights_filters(filtering, campaign_id, campaign_name, adset_id, ad_id)
    if filters:
        params["filtering"] = filters
    if sort:
        params["sort"] = sort
    if after:
        params["after"] = after

    try:
        payload = fetch_insights_payload(
            account_id,
            token,
            params=params,
            max_pages=max_pages if fetch_all else min(max_pages, 3),
        )
        if not fetch_all:
            payload["data"] = payload.get("data", [])[: int(limit or DEFAULT_PAGE_LIMIT)]
        return payload
    except Exception as exc:
        return {
            "data": [],
            "available": False,
            "source": "meta_insights",
            "diagnostic": {
                "message": "Meta Insights remained unavailable after the server tried direct object, lightweight, minimal, and local-filter fallbacks.",
                "account_id": account_id,
                "level": level,
                "campaign_id": campaign_id,
                "adset_id": adset_id,
                "ad_id": ad_id,
                "date_preset": date_preset,
                "time_range": time_range,
                "error": str(getattr(exc, "detail", exc))[:4000],
                "next_step": "Use this diagnostic to identify the Meta Graph rejection. Do not retry the same broad request.",
            },
        }


def _build_insights_filters(
    filtering: str | None,
    campaign_id: str | None,
    campaign_name: str | None,
    adset_id: str | None,
    ad_id: str | None,
) -> list[dict]:
    filters = _parse_filtering(filtering)
    if campaign_id:
        filters.append({"field": "campaign.id", "operator": "IN", "value": [_clean(campaign_id)]})
    if campaign_name:
        filters.append({"field": "campaign.name", "operator": "CONTAIN", "value": _clean(campaign_name)})
    if adset_id:
        filters.append({"field": "adset.id", "operator": "IN", "value": [_clean(adset_id)]})
    if ad_id:
        filters.append({"field": "ad.id", "operator": "IN", "value": [_clean(ad_id)]})
    return filters


def _parse_filtering(filtering: str | None) -> list[dict]:
    text = _clean(filtering)
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, dict):
        return [parsed]
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    return []


def _local_filter_rows(
    rows: list[dict],
    campaign_id: str | None,
    campaign_name: str | None,
    adset_id: str | None,
    ad_id: str | None,
) -> list[dict]:
    result = []
    for row in rows:
        if campaign_id and _clean(row.get("campaign_id")) != _clean(campaign_id):
            continue
        if campaign_name and _clean(campaign_name).lower() not in _clean(row.get("campaign_name")).lower():
            continue
        if adset_id and _clean(row.get("adset_id")) != _clean(adset_id):
            continue
        if ad_id and _clean(row.get("ad_id")) != _clean(ad_id):
            continue
        result.append(row)
    return result


def _clean(value) -> str:
    return str(value or "").strip()
