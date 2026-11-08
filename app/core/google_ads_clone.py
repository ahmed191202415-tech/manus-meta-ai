"""Guarded one-command campaign clone preview via Google's official Python SDK.

Google Ads has no universal Duplicate Campaign API method. A faithful clone
requires reading every applicable setting, copying supported resources, and
reviewing noncopyable associations. This endpoint does not mutate.
"""
from __future__ import annotations

import re
from fastapi import HTTPException

from app.core.google_ads_sdk import _safe_customer_id, sdk_search

_PREVIEW_QUERIES = {
    "account": ("SELECT customer.id, customer.currency_code FROM customer LIMIT 1", 2),
    "campaign": (
        "SELECT campaign.id, campaign.name, campaign.status, campaign.advertising_channel_type, "
        "campaign.bidding_strategy_type, campaign.campaign_budget, campaign_budget.amount_micros, "
        "campaign.network_settings.target_google_search, campaign.network_settings.target_search_network, "
        "campaign.network_settings.target_partner_search_network, campaign.network_settings.target_content_network "
        "FROM campaign WHERE campaign.id = {source} LIMIT 2", 2),
    "ad_group": (
        "SELECT ad_group.id, ad_group.campaign, ad_group.name, ad_group.status, ad_group.type "
        "FROM ad_group WHERE ad_group.id = {group} AND campaign.id = {source} LIMIT 2", 2),
    "keywords": (
        "SELECT ad_group_criterion.criterion_id, ad_group_criterion.status, "
        "ad_group_criterion.negative, ad_group_criterion.keyword.text, "
        "ad_group_criterion.keyword.match_type FROM ad_group_criterion "
        "WHERE ad_group.id = {group} AND ad_group_criterion.type = 'KEYWORD' "
        "AND ad_group_criterion.status != 'REMOVED' LIMIT 250", 250),
    "ads": (
        "SELECT ad_group_ad.ad.id, ad_group_ad.status, ad_group_ad.ad.type, "
        "ad_group_ad.ad.final_urls, ad_group_ad.ad.responsive_search_ad.headlines, "
        "ad_group_ad.ad.responsive_search_ad.descriptions, "
        "ad_group_ad.ad.responsive_search_ad.path1, ad_group_ad.ad.responsive_search_ad.path2 "
        "FROM ad_group_ad WHERE ad_group.id = {group} AND ad_group_ad.status != 'REMOVED' LIMIT 200", 200),
    "campaign_exclusions": (
        "SELECT campaign_criterion.criterion_id, campaign_criterion.type, campaign_criterion.negative, "
        "campaign_criterion.status FROM campaign_criterion WHERE campaign.id = {source} "
        "AND campaign_criterion.status != 'REMOVED' LIMIT 250", 250),
    "ad_group_targets": (
        "SELECT ad_group_criterion.criterion_id, ad_group_criterion.type, "
        "ad_group_criterion.status, ad_group_criterion.negative FROM ad_group_criterion "
        "WHERE ad_group.id = {group} AND ad_group_criterion.type != 'KEYWORD' "
        "AND ad_group_criterion.status != 'REMOVED' LIMIT 250", 250),
    "campaign_assets": (
        "SELECT campaign_asset.asset, campaign_asset.field_type, campaign_asset.status "
        "FROM campaign_asset WHERE campaign.id = {source} "
        "AND campaign_asset.status != 'REMOVED' LIMIT 250", 250),
    "ad_group_assets": (
        "SELECT ad_group_asset.asset, ad_group_asset.field_type, ad_group_asset.status "
        "FROM ad_group_asset WHERE ad_group.id = {group} "
        "AND ad_group_asset.status != 'REMOVED' LIMIT 250", 250),
    "shared_negative_sets": (
        "SELECT campaign_shared_set.shared_set, campaign_shared_set.status "
        "FROM campaign_shared_set WHERE campaign.id = {source} "
        "AND campaign_shared_set.status != 'REMOVED' LIMIT 250", 250),
    "existing_target_name": (
        "SELECT campaign.id, campaign.name FROM campaign "
        "WHERE campaign.name = '{dest}' LIMIT 2", 2),
}


def preview_clone_campaign(tenant: str, request: dict) -> dict:
    cid = _safe_customer_id(request.get("customer_id"))
    src = str(request.get("source_campaign_id") or "").strip()
    groups = request.get("keep_ad_group_ids")
    name = str(request.get("new_campaign_name") or "").strip()
    micros = request.get("daily_budget_micros")
    if type(request.get("dry_run")) is not bool or request["dry_run"] is not True:
        raise HTTPException(403, "Only dry_run=true is enabled. No live clone is authorized.")
    if request.get("status") != "PAUSED":
        raise HTTPException(422, "New clone campaign must be PAUSED.")
    if not src.isascii() or not src.isdecimal() or not (1 <= len(src) <= 20):
        raise HTTPException(422, "source_campaign_id must be a numeric campaign ID.")
    if not isinstance(groups, list) or len(groups) != 1:
        raise HTTPException(422, "keep_ad_group_ids must contain exactly one ad group ID.")
    group = str(groups[0])
    if not group.isascii() or not group.isdecimal() or not (1 <= len(group) <= 20):
        raise HTTPException(422, "Invalid ad group ID.")
    if not re.fullmatch(r"[a-zA-Z0-9 _.-]{1,80}", name):
        raise HTTPException(422, "new_campaign_name must be 1-80 plain letters/numbers.")
    if type(micros) is not int or not (1_000_000 <= micros <= 10_000_000_000):
        raise HTTPException(422, "daily_budget_micros must be a positive integer of 1 to 10000 units.")
    if request.get("manager_id"):
        _safe_customer_id(request["manager_id"])
    fields = {"source": src, "group": group, "dest": name}
    sections = {}
    failed = []
    incomplete = []
    for key, (q, max_rows) in _PREVIEW_QUERIES.items():
        try:
            res = sdk_search(
                tenant, cid, q.format(**fields),
                manager_id=request.get("manager_id"), limit=max_rows,
            )
            rows = res.get("rows") or []
            truncated = bool(res.get("truncated")) or len(rows) >= max_rows
            sections[key] = {"ok": True, "count": len(rows), "truncated": truncated}
            if truncated:
                incomplete.append(key)
            if key in {"account", "campaign", "ad_group", "existing_target_name"}:
                sections[key]["rows"] = rows[:2]
            if key == "keywords":
                sections[key]["sample_keywords"] = [
                    {"text": (r.get("adGroupCriterion") or {}).get("keyword", {}).get("text"),
                     "match_type": (r.get("adGroupCriterion") or {}).get("keyword", {}).get("matchType"),
                     "status": (r.get("adGroupCriterion") or {}).get("status")}
                    for r in rows[:5]
                ]
            if key == "ads":
                sections[key]["ad_types"] = sorted({
                    str((r.get("adGroupAd") or {}).get("ad", {}).get("type") or "UNKNOWN")
                    for r in rows
                })
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            code = detail.get("google_ads_error_code")
            if not isinstance(code, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{2,79}", code):
                code = "UNSPECIFIED"
            sections[key] = {
                "ok": False,
                "error": {"http_status": exc.status_code, "code": code},
            }
            failed.append(key)

    account_rows = sections.get("account", {}).get("rows") or []
    campaign_rows = sections.get("campaign", {}).get("rows") or []
    group_rows = sections.get("ad_group", {}).get("rows") or []
    dest_rows = sections.get("existing_target_name", {}).get("rows") or []
    currency = (account_rows[0].get("customer") or {}).get("currencyCode") if account_rows else None
    camp = campaign_rows[0].get("campaign") or {} if campaign_rows else {}
    ad_group = group_rows[0].get("adGroup") or {} if group_rows else {}
    identity_ok = (
        str(camp.get("id") or "") == src
        and str(ad_group.get("id") or "") == group
        and str(ad_group.get("campaign") or "") == f"customers/{cid}/campaigns/{src}"
    )
    blockers = []
    if not identity_ok:
        blockers.append("SOURCE_CAMPAIGN_OR_AD_GROUP_NOT_VERIFIED")
    if currency != "EGP":
        blockers.append("EXPECTED_EGP_CURRENCY_NOT_VERIFIED")
    if str(camp.get("advertisingChannelType") or "") != "SEARCH":
        blockers.append("SOURCE_MUST_BE_SEARCH")
    if dest_rows:
        blockers.append("DESTINATION_CAMPAIGN_NAME_ALREADY_EXISTS")
    if failed:
        blockers.append("READ_FAILURES")
    if incomplete:
        blockers.append("INCOMPLETE_PAGINATION")
    blockers.append("FULL_FIDELITY_CLONE_WRITES_NOT_YET_IMPLEMENTED")
    return {
        "ok": not failed and identity_ok,
        "provider": "google_ads",
        "action": "clone_campaign",
        "mode": "DRY_RUN",
        "google_api_client": "official-google-ads-python",
        "no_changes_applied": True,
        "source": {"customer_id": cid, "campaign_id": src, "ad_group_ids": [group]},
        "proposed": {
            "campaign_name": name, "status": "PAUSED",
            "daily_budget_micros": micros,
            "daily_budget_egp": micros / 1_000_000,
            "independent_budget": True, "only_ad_group_id": group,
            "original_campaign_unchanged": True,
        },
        "verified_source_identity": identity_ok,
        "sections": sections,
        "failed_sections": failed,
        "truncated_sections": incomplete,
        "blockers": blockers,
        "ready_for_execution": False,
        "next_step": (
            "Review the source details and implement a validated faithful clone. "
            "No new campaign can be created with this dry-run action."
        ),
    }
