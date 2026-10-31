"""Live Google Ads account discovery and campaign inspection, read-only.

Uses GoogleAdsService through the existing tenant-scoped Google Ads gateway.
Exposes all data through the already published /tools/intent GPT Action.
Never estimates identifiers, budgets, account names or currency.
"""
from __future__ import annotations

import re
from fastapi import HTTPException

MAX_DIRECT_ACCOUNTS = 8
MAX_CLIENT_ACCOUNTS = 25
MAX_CAMPAIGNS_TO_INSPECT = 3
SAFE_CAMPAIGN_NAME = re.compile(r"^[\w .&()\-]{1,90}$", re.UNICODE)


def _client_id_from_resource(resource: str) -> str | None:
    match = re.fullmatch(r"customers/([0-9]{10})", str(resource or ""))
    return match.group(1) if match else None


def _safe_google_ads_error(exc: HTTPException) -> dict:
    """Return only the safe structured error enums from the Google Ads gateway."""
    raw = exc.detail if isinstance(exc.detail, dict) else {}
    return {
        "http_status": exc.status_code,
        "origin": raw.get("origin") if raw.get("origin") == "google_ads_api" else "unknown",
        "api_status": raw.get("api_status") or "UNKNOWN",
        "google_ads_error_code": raw.get("google_ads_error_code") or "UNSPECIFIED",
        "next_step": raw.get("next_step") or "Check Google Ads API access and account status.",
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
                " customer.manager, customer.status FROM customer LIMIT 1",
                tenant, cid, manager_id=None, limit=1,
            )
            customer = (info.get("rows") or [{}])[0].get("customer") or {}
            manager = bool(customer.get("manager", False))
            accounts.append({
                "customer_id": cid,
                "name": customer.get("descriptiveName"),
                "currency": customer.get("currencyCode"),
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
    tenant: str, campaign_name: str, customer_id=None, manager_id=None,
    date_range: str = "LAST_7_DAYS",
) -> dict:
    from app.core.google_ads_gateway import _read, _customer_id, DURATIONS

    name = str(campaign_name or "").strip()
    if not SAFE_CAMPAIGN_NAME.fullmatch(name):
        raise HTTPException(422, "Campaign name must be 1-90 letters/numbers/spaces/hyphens without quotes.")
    if date_range not in DURATIONS:
        raise HTTPException(422, "Unsupported date range.")
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
        query=(
            "SELECT campaign.id, campaign.name, campaign.status,"
            " campaign.campaign_budget, campaign.advertising_channel_type,"
            " campaign_budget.amount_micros, campaign_budget.explicitly_shared"
            " FROM campaign WHERE campaign.name = '" + name + "' LIMIT 10"
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
            if str(campaign.get("name") or "").casefold()!=name.casefold():
                continue
            budget=row.get("campaignBudget") or {}
            camp_id=str(campaign.get("id") or "")
            if not camp_id.isdigit():
                continue
            groups_query=(
                "SELECT campaign.id, ad_group.id, ad_group.name, ad_group.status,"
                " metrics.cost_micros, metrics.impressions, metrics.clicks, metrics.conversions"
                f" FROM ad_group WHERE campaign.id = {camp_id}"
            )
            if date_range != "ALL_TIME":
                groups_query+=f" AND segments.date DURING {date_range}"
            groups_query+=" LIMIT 100"
            groups_truncated = False
            try:
                groups=_read(groups_query, tenant, cid, mid, limit=100)
                groups_truncated = bool(groups.get("truncated"))
                ad_groups=[
                    {
                        "id": (g.get("adGroup") or {}).get("id"),
                        "name": (g.get("adGroup") or {}).get("name"),
                        "status": (g.get("adGroup") or {}).get("status"),
                        "metrics": g.get("metrics") or {},
                    }
                    for g in groups.get("rows") or []
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
                "currency": candidate.get("currency"),
                "manager_id": mid,
                "campaign_id": camp_id,
                "campaign_name": campaign.get("name"),
                "status": campaign.get("status"),
                "budget_resource": campaign.get("campaignBudget"),
                "budget_micros": budget.get("amountMicros"),
                "budget_shared": budget.get("explicitlyShared"),
                "ad_groups": ad_groups,
                "ad_groups_truncated": groups_truncated,
            })
            if len(found) >= MAX_CAMPAIGNS_TO_INSPECT:
                break
        if len(found) >= MAX_CAMPAIGNS_TO_INSPECT:
            break
    return {
        "provider":"google_ads", "action":"inspect_campaign",
        "verified_by_google_api": True,
        "campaign_data_verified": bool(found),
        "campaign_name":name,
        "campaigns":found, "accounts_checked":checked,
        "account_errors": account_errors, "warnings":warnings,
        "note": (
            "Budgets are at campaign level, not ad-group level. If crm is an ad group,"
            " assigning it its own EGP 800/day budget requires a separate campaign and"
            " a reviewed migration plan. This endpoint does not change any campaign."
        ),
        "next_step": (
            "Resolve account_errors first. Google Ads has not provided any verified campaign data."
            if not found and account_errors
            else "Review exact customer, campaign and group IDs. No mutations have been applied."
        ),
    }
