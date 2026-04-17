from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends

from app.config import DEFAULT_PAGE_LIMIT, DEFAULT_MAX_PAGES
from app.core.auth import resolve_access_token
from app.core.pagination import meta_get_all_pages
from app.core.meta_client import meta_call, normalize_account_id
from app.analytics.preprocessing import DEFAULT_INSIGHTS_FIELDS

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

    if fetch_all:
        return meta_get_all_pages(f"{account_id}/insights", token, params=params, max_pages=max_pages)

    return meta_call("GET", f"{account_id}/insights", token, params=params)
