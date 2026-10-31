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
            warnings.append(f"Account {cid} inspection returned HTTP {exc.status_code}.")
            accounts.append({"customer_id": cid, "name": None, "access": "direct", "details_unavailable": True})
    if len(direct_ids)>MAX_DIRECT_ACCOUNTS:
        warnings.append(f"Limited direct-account detail discovery to {MAX_DIRECT_ACCOUNTS}; request a specific customer ID for other accounts.")
    if len(accounts)>MAX_CLIENT_ACCOUNTS:
        warnings.append(f"Only showing the first {MAX_CLIENT_ACCOUNTS} linked accounts; specify customer_id for the remainder.")
        accounts=accounts[:MAX_CLIENT_ACCOUNTS]
    return {
        "provider": "google_ads", "action": "list_accounts",
        "verified_by_google_api": True,
        "direct_count": len(direct_ids),
        "accounts": accounts,
        "warnings": warnings,
        "next_step": "Use inspect_campaign with campaign_name for server-side campaign and ad group discovery, or report/query with a customer_id.",
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
            warnings.append(f"Campaign lookup in account {cid} failed with HTTP {exc.status_code}.")
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
            try:
                groups=_read(groups_query, tenant, cid, mid, limit=100)
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
                warnings.append(f"Ad group lookup for campaign {camp_id} returned HTTP {exc.status_code}.")
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
                "ad_groups_truncated": bool(groups.get("truncated")) if "groups" in locals() else False,
            })
            if len(found) >= MAX_CAMPAIGNS_TO_INSPECT:
                break
        if len(found) >= MAX_CAMPAIGNS_TO_INSPECT:
            break
    return {
        "provider":"google_ads", "action":"inspect_campaign",
        "verified_by_google_api": True, "campaign_name":name,
        "campaigns":found, "accounts_checked":checked, "warnings":warnings,
        "note": (
            "Budgets are at campaign level, not ad-group level. If crm is an ad group,"
            " assigning it its own EGP 800/day budget requires a separate campaign and"
            " a reviewed migration plan. This endpoint does not change any campaign."
        ),
        "next_step": "Review exact customer, campaign and group IDs. No mutations have been applied.",
    }
