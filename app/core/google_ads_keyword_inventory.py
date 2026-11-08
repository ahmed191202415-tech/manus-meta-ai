"""Read-only, tightly scoped Google Ads keyword inventory and 30-day performance.

No campaign mutations, no ad-group discovery via natural-language guesses.
Queries use a fixed GAQL template and server-side validated numeric identifiers.
"""
from __future__ import annotations

import re
from fastapi import HTTPException

MAX_KEYWORDS = 1000
VALID_ID = re.compile(r"^[0-9]{1,20}$")

def _id(value: object, field: str) -> str:
    cleaned = str(value or "").strip()
    if not VALID_ID.fullmatch(cleaned):
        raise HTTPException(422, f"{field} must be a numeric Google Ads identifier.")
    return cleaned

def _check(row: dict, campaign_id: str, group_id: str) -> None:
    campaign = row.get("campaign") or {}
    group = row.get("adGroup") or {}
    if str(campaign.get("id", "")) != campaign_id or str(group.get("id", "")) != group_id:
        raise HTTPException(502, "Google Ads returned a row outside the requested campaign/ad group; results withheld.")

def _criterion_id(row: dict) -> str:
    criterion = row.get("adGroupCriterion") or {}
    value = criterion.get("criterionId")
    if value is None:
        raise HTTPException(502, "Google Ads omitted keyword criterion ID.")
    return str(value)

def _list(query: str, *, tenant: str, customer_id: str, manager_id=None) -> list[dict]:
    # Reuse the existing OAuth, error handling and REST adapter from Oct 31.
    # Do not return silently truncated inventories.
    from app.core.google_ads_gateway import _api
    rows = []
    token = None
    seen = set()
    while True:
        payload = {"query": query, "pageSize": 1000}
        if token:
            payload["pageToken"] = token
        response = _api(tenant, "POST", f"/customers/{customer_id}/googleAds:search", payload, manager_id=manager_id)
        page = response.get("results") or []
        if not isinstance(page, list):
            raise HTTPException(502, "Invalid Google Ads keyword response.")
        rows.extend(page)
        if len(rows) > MAX_KEYWORDS:
            raise HTTPException(422, "Keyword inventory exceeded safety limit; results withheld.")
        following = response.get("nextPageToken")
        if not following:
            return rows
        if following in seen:
            raise HTTPException(502, "Repeated Google Ads page token; results withheld.")
        seen.add(following)
        token = following

def read_keyword_inventory(tenant: str, args: dict) -> dict:
    """Inventory (no date filter) + performance, joined by criterion ID."""
    from app.core.google_ads_gateway import _customer_id
    customer_id = _customer_id(args.get("customer_id"))
    campaign_id = _id(args.get("campaign_id"), "campaign_id")
    group_id = _id(args.get("ad_group_id"), "ad_group_id")
    manager_id = args.get("manager_id")
    filters = (f"campaign.id = {campaign_id} AND ad_group.id = {group_id} "
               "AND ad_group_criterion.type = KEYWORD "
               "AND ad_group_criterion.status = ENABLED "
               "AND ad_group_criterion.negative = FALSE")
    inventory_query = (
        "SELECT campaign.id, ad_group.id, ad_group_criterion.criterion_id, "
        "ad_group_criterion.keyword.text, ad_group_criterion.keyword.match_type, "
        "ad_group_criterion.status, ad_group_criterion.quality_info.quality_score, "
        "ad_group_criterion.quality_info.search_predicted_ctr, "
        "ad_group_criterion.quality_info.creative_quality_score, "
        "ad_group_criterion.quality_info.post_click_quality_score "
        "FROM ad_group_criterion WHERE " + filters
    )
    performance_query = (
        "SELECT campaign.id, ad_group.id, ad_group_criterion.criterion_id, "
        "metrics.impressions, metrics.clicks, metrics.ctr, metrics.cost_micros, "
        "metrics.conversions FROM keyword_view WHERE " + filters
        + " AND segments.date DURING LAST_30_DAYS"
    )
    inventory_rows = _list(inventory_query, tenant=tenant, customer_id=customer_id, manager_id=manager_id)
    result = {}
    for row in inventory_rows:
        _check(row, campaign_id, group_id)
        criterion = row.get("adGroupCriterion") or {}
        key = _criterion_id(row)
        if key in result:
            raise HTTPException(502, "Duplicate keyword criterion ID in inventory.")
        kw = criterion.get("keyword") or {}
        qi = criterion.get("qualityInfo") or {}
        result[key] = {
            "criterion_id": key, "keyword": kw.get("text"),
            "match_type": kw.get("matchType"), "status": criterion.get("status"),
            "quality_score": qi.get("qualityScore"),
            "expected_ctr": qi.get("searchPredictedCtr"),
            "ad_relevance": qi.get("creativeQualityScore"),
            "landing_page_experience": qi.get("postClickQualityScore"),
            "impressions": 0, "clicks": 0, "cost_micros": 0, "conversions": 0,
        }
    performance_rows = _list(performance_query, tenant=tenant, customer_id=customer_id, manager_id=manager_id)
    for row in performance_rows:
        _check(row, campaign_id, group_id)
        key = _criterion_id(row)
        if key not in result:
            raise HTTPException(502, "Performance row has no matching active keyword; results withheld.")
        metrics = row.get("metrics") or {}
        record = result[key]
        record["impressions"] += int(metrics.get("impressions") or 0)
        record["clicks"] += int(metrics.get("clicks") or 0)
        record["cost_micros"] += int(metrics.get("costMicros") or 0)
        record["conversions"] += float(metrics.get("conversions") or 0)
    for record in result.values():
        record["ctr"] = (record["clicks"] / record["impressions"]) if record["impressions"] else 0
    return {
        "ok": True, "provider": "google_ads", "report": "keyword_inventory",
        "customer_id": customer_id, "campaign_id": campaign_id, "ad_group_id": group_id,
        "date_range": "LAST_30_DAYS", "source": "Google Ads API",
        "inventory_complete": True, "scope_verified": True,
        "count": len(result), "keywords": list(result.values()),
    }
