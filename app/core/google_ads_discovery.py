"""Live Google Ads account discovery and campaign inspection, read-only.

Uses GoogleAdsService through the existing tenant-scoped Google Ads gateway.
Exposes all data through the already published /tools/intent GPT Action.
Never estimates identifiers, budgets, account names or currency.
"""
from __future__ import annotations

import re
from fastapi import HTTPException

from app.core.google_ads_reporting import DURATIONS, _date, _id

MAX_DIRECT_ACCOUNTS = 8
MAX_CLIENT_ACCOUNTS = 25
MAX_CAMPAIGNS_TO_INSPECT = 3
SAFE_CAMPAIGN_NAME = re.compile(r"^[\w .&()\-]{1,90}$", re.UNICODE)


def _client_id_from_resource(resource: str) -> str | None:
    match = re.fullmatch(r"customers/([0-9]{10})", str(resource or ""))
    return match.group(1) if match else None


def _safe_google_ads_error(exc: HTTPException) -> dict:
    """Keep safe structured diagnostics across account and campaign discovery."""
    raw = exc.detail if isinstance(exc.detail, dict) else {}
    def enum(value, fallback):
        return value if isinstance(value, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{2,79}", value) else fallback
    request_id = raw.get("google_request_id")
    if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{4,100}", request_id):
        request_id = None
    field = raw.get("google_ads_error_field")
    if not isinstance(field, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.\[\]]{0,149}", field):
        field = None
    category = raw.get("google_ads_error_category")
    if category not in {"query", "access", "authentication", "quota", "transient", "request", "configuration", "validation", "unknown"}:
        category = "unknown"
    next_step = raw.get("next_step")
    return {
        "http_status": exc.status_code,
        "origin": raw.get("origin") if raw.get("origin") in {"google_ads_api", "google_ads_official_sdk"} else "unknown",
        "api_status": enum(raw.get("api_status"), "UNKNOWN"),
        "google_ads_error_code": enum(raw.get("google_ads_error_code"), "UNSPECIFIED"),
        "google_ads_error_category": category,
        "google_ads_error_field": field,
        "google_request_id": request_id,
        "next_step": next_step[:500] if isinstance(next_step, str) else "Use the structured Google Ads error to diagnose this failed read.",
    }


def list_accounts_live(tenant: str, manager_id=None, expand_clients: bool = True) -> dict:
    from app.core.google_ads_gateway import _api, _read, _customer_id

    result = _api(tenant, "GET", "/customers:listAccessibleCustomers")
    direct_ids = []
    for resource in result.get("resourceNames") or []:
        cid = _client_id_from_resource(resource)
        if cid and cid not in direct_ids:
            direct_ids.append(cid)
    accounts = []
    warnings = []
    for cid in direct_ids[:MAX_DIRECT_ACCOUNTS]:
        try:
            info = _read(
                "SELECT customer.id, customer.descriptive_name, customer.currency_code,"
                " customer.time_zone, customer.manager, customer.status FROM customer LIMIT 1",
                tenant, cid, manager_id=None, limit=1,
            )
            customer = (info.get("rows") or [{}])[0].get("customer") or {}
            manager = bool(customer.get("manager", False))
            accounts.append({
                "customer_id": cid,
                "name": customer.get("descriptiveName"),
                "currency": customer.get("currencyCode"),
                "time_zone": customer.get("timeZone"),
                "manager": manager,
                "access": "direct",
            })
            if expand_clients and manager:
                children = _read(
                    "SELECT customer_client.id, customer_client.descriptive_name,"
                    " customer_client.currency_code, customer_client.manager,"
                    " customer_client.level FROM customer_client"
                    " WHERE customer_client.level = 1 LIMIT 50",
                    tenant, cid, manager_id=None, limit=50,
                )
                for row in children.get("rows") or []:
                    client = row.get("customerClient") or {}
                    child_id = str(client.get("id") or "")
                    if re.fullmatch(r"[0-9]{10}", child_id) and child_id != cid:
                        accounts.append({
                            "customer_id": child_id,
                            "name": client.get("descriptiveName"),
                            "currency": client.get("currencyCode"),
                            "manager": bool(client.get("manager")),
                            "access": "via_manager",
                            "manager_id": cid,
                        })
                if children.get("truncated"):
                    warnings.append("Manager account client listing was truncated.")
        except HTTPException as exc:
            details_error = _safe_google_ads_error(exc)
            warnings.append(
                f"Account {cid} detail read failed: HTTP {exc.status_code} "
                f"{details_error['google_ads_error_code']}."
            )
            accounts.append({
                "customer_id": cid, "name": None, "access": "direct",
                "details_unavailable": True, "details_error": details_error,
            })
    if len(direct_ids)>MAX_DIRECT_ACCOUNTS:
        warnings.append(f"Limited direct-account detail discovery to {MAX_DIRECT_ACCOUNTS}; request a specific customer ID for other accounts.")
    if len(accounts)>MAX_CLIENT_ACCOUNTS:
        warnings.append(f"Only showing the first {MAX_CLIENT_ACCOUNTS} linked accounts; specify customer_id for the remainder.")
        accounts=accounts[:MAX_CLIENT_ACCOUNTS]
    return {
        "provider": "google_ads", "action": "list_accounts",
        "verified_by_google_api": True,
        "account_list_verified": True,
        "account_details_verified": sum(
            1 for account in accounts
            if account.get("access") == "direct" and not account.get("details_unavailable")
        ),
        "direct_count": len(direct_ids),
        "accounts": accounts,
        "warnings": warnings,
        "next_step": (
            "Resolve each details_error.google_ads_error_code before inspecting campaigns."
            if any(a.get("details_unavailable") for a in accounts)
            else "Use inspect_campaign with campaign_name for server-side campaign and ad group discovery."
        ),
    }


def inspect_campaign_live(
    tenant: str, campaign_name: str | None = None, customer_id=None, manager_id=None,
    date_range: str = "LAST_7_DAYS", *, date=None, start_date=None, end_date=None,
    campaign_id=None,
) -> dict:
    from app.core.google_ads_gateway import _read, _customer_id

    name = str(campaign_name or "").strip()
    if name and not SAFE_CAMPAIGN_NAME.fullmatch(name):
        raise HTTPException(422, "Campaign name must be 1-90 letters/numbers/spaces/hyphens without quotes.")
    requested_id = _id(campaign_id, "campaign_id") if campaign_id not in (None, "") else None
    if not name and not requested_id:
        raise HTTPException(422, "Supply campaign_name or campaign_id for campaign inspection.")
    has_date = date not in (None, "")
    has_start, has_end = start_date not in (None, ""), end_date not in (None, "")
    if has_date and (has_start or has_end):
        raise HTTPException(422, "Use either date or start_date/end_date, not both.")
    if has_start != has_end:
        raise HTTPException(422, "Supply both start_date and end_date for an inclusive date range.")
    if has_date:
        start_date = end_date = _date(date, "date")
        period_mode = "date"
        date_range = start_date
        date_filter = f"segments.date = '{start_date}'"
    elif has_start:
        start_date, end_date = _date(start_date, "start_date"), _date(end_date, "end_date")
        if start_date > end_date:
            raise HTTPException(422, "start_date must not be after end_date.")
        period_mode = "inclusive_range"
        date_range = f"{start_date}..{end_date}"
        date_filter = f"segments.date BETWEEN '{start_date}' AND '{end_date}'"
    else:
        date_range = str(date_range or "LAST_7_DAYS").upper()
        if date_range not in DURATIONS:
            raise HTTPException(422, "Unsupported date_range for inspection metrics. Use a supported preset or explicit start_date/end_date; ALL_TIME is not supported.")
        start_date = end_date = None
        period_mode = "preset"
        date_filter = f"segments.date DURING {date_range}"
    period = {
        "mode": period_mode, "start_date": start_date, "end_date": end_date,
        "preset": date_range if period_mode == "preset" else None,
        "time_zone_basis": "customer.time_zone",
    }
    if customer_id:
        candidates=[{"customer_id": _customer_id(customer_id), "manager_id": _customer_id(manager_id) if manager_id else None}]
        accounts={"accounts": candidates, "warnings": []}
    else:
        accounts=list_accounts_live(tenant)
        candidates=accounts["accounts"]
    found=[]
    checked=0
    warnings=list(accounts.get("warnings") or [])
    account_errors = []
    for candidate in candidates:
        if candidate.get("details_unavailable") and candidate.get("details_error"):
            account_errors.append({
                "customer_id": candidate["customer_id"],
                "stage": "account_details",
                **candidate["details_error"],
            })
    for candidate in candidates[:MAX_CLIENT_ACCOUNTS]:
        cid=candidate["customer_id"]
        mid=candidate.get("manager_id") or (manager_id if manager_id else None)
        conditions = []
        if name:
            conditions.append("campaign.name = '" + name + "'")
        if requested_id:
            conditions.append(f"campaign.id = {requested_id}")
        query=(
            "SELECT customer.id, customer.currency_code, customer.time_zone,"
            " campaign.id, campaign.name, campaign.status,"
            " campaign.campaign_budget, campaign.advertising_channel_type,"
            " campaign_budget.amount_micros, campaign_budget.explicitly_shared"
            " FROM campaign WHERE " + " AND ".join(conditions) + " LIMIT 10"
        )
        try:
            res=_read(query, tenant, cid, mid, limit=10)
            checked+=1
        except HTTPException as exc:
            safe = _safe_google_ads_error(exc)
            account_errors.append({"customer_id": cid, "stage": "campaign_lookup", **safe})
            warnings.append(
                f"Campaign lookup in account {cid} failed: HTTP {exc.status_code} "
                f"{safe['google_ads_error_code']}."
            )
            continue
        for row in res.get("rows") or []:
            campaign=row.get("campaign") or {}
            if name and str(campaign.get("name") or "").casefold() != name.casefold():
                continue
            if requested_id and str(campaign.get("id") or "") != requested_id:
                raise HTTPException(502, "Google Ads returned a campaign outside the requested ID; results withheld.")
            budget=row.get("campaignBudget") or {}
            camp_id=str(campaign.get("id") or "")
            if not camp_id.isdigit():
                continue
            groups_query=(
                "SELECT campaign.id, ad_group.id, ad_group.name, ad_group.status,"
                " metrics.cost_micros, metrics.impressions, metrics.clicks, metrics.conversions"
                f" FROM ad_group WHERE campaign.id = {camp_id}"
            )
            groups_query += " AND " + date_filter
            groups_query+=" LIMIT 101"
            groups_truncated = False
            groups_verified = False
            try:
                groups=_read(groups_query, tenant, cid, mid, limit=101)
                groups_truncated = bool(groups.get("truncated")) or len(groups.get("rows") or []) > 100
                groups_verified = True
                ad_groups=[
                    {
                        "id": (g.get("adGroup") or {}).get("id"),
                        "name": (g.get("adGroup") or {}).get("name"),
                        "status": (g.get("adGroup") or {}).get("status"),
                        "metrics": g.get("metrics") or {},
                    }
                    for g in (groups.get("rows") or [])[:100]
                ]
            except HTTPException as exc:
                ad_groups=[]
                safe = _safe_google_ads_error(exc)
                account_errors.append({
                    "customer_id": cid, "stage": "ad_group_lookup",
                    "campaign_id": camp_id, **safe,
                })
                warnings.append(
                    f"Ad group lookup for campaign {camp_id} failed: HTTP {exc.status_code} "
                    f"{safe['google_ads_error_code']}."
                )
            found.append({
                "customer_id": cid,
                "account_name": candidate.get("name"),
                "currency": candidate.get("currency") or (row.get("customer") or {}).get("currencyCode"),
                "time_zone": candidate.get("time_zone") or (row.get("customer") or {}).get("timeZone"),
                "manager_id": mid,
                "campaign_id": camp_id,
                "campaign_name": campaign.get("name"),
                "status": campaign.get("status"),
                "budget_resource": campaign.get("campaignBudget"),
                "budget_micros": budget.get("amountMicros"),
                "budget_shared": budget.get("explicitlyShared"),
                "ad_groups": ad_groups,
                "ad_groups_truncated": groups_truncated,
                "ad_groups_verified": groups_verified,
                "metrics_date_range": date_range,
                "metrics_period": dict(period),
            })
            if len(found) >= MAX_CAMPAIGNS_TO_INSPECT:
                break
        if len(found) >= MAX_CAMPAIGNS_TO_INSPECT:
            break
    return {
        "provider":"google_ads", "action":"inspect_campaign",
        "verified_by_google_api": checked > 0,
        "google_api_called": checked > 0 or any(e.get("origin") == "google_ads_api" for e in account_errors),
        "campaign_data_verified": bool(found),
        "read_complete": not account_errors and not any(c["ad_groups_truncated"] for c in found),
        "date_range": date_range,
        "start_date": start_date, "end_date": end_date, "period": period,
        "metrics_scope": "ad_groups",
        "no_changes_applied": True,
        "campaign_name": name or None, "campaign_id": requested_id,
        "campaigns":found, "accounts_checked":checked,
        "account_errors": account_errors, "warnings":warnings,
        "note": (
            "This is campaign configuration and ad-group performance for the stated date_range. "
            "It is not a campaign performance report. Budgets are at campaign level. "
            "This endpoint does not change any campaign."
        ),
        "next_step": (
            "Resolve account_errors first. Google Ads has not provided any verified campaign data."
            if not found and account_errors
            else "Review exact customer, campaign and group IDs. No mutations have been applied."
        ),
    }
