"""Read-only audit for separating one Google Ads ad group into a campaign.

No mutations, copied entities, forecasts, or inferred settings. Sections can
fail independently; never represent partial read results as clone-ready.
"""
from __future__ import annotations

from fastapi import HTTPException

from app.core.google_ads_discovery import _safe_google_ads_error

SECTIONS = (
    ("campaign", "SELECT campaign.id, campaign.name, campaign.status, campaign.advertising_channel_type, campaign.bidding_strategy_type, campaign.maximize_conversions.target_cpa_micros, campaign.network_settings.target_google_search, campaign.network_settings.target_search_network, campaign.network_settings.target_partner_search_network, campaign.network_settings.target_content_network, campaign.geo_target_type_setting.positive_geo_target_type, campaign.geo_target_type_setting.negative_geo_target_type, campaign.campaign_budget, campaign_budget.amount_micros, campaign.tracking_url_template, campaign.final_url_suffix FROM campaign WHERE campaign.id = {campaign} LIMIT 2", 2),
    ("ad_group", "SELECT campaign.id, ad_group.id, ad_group.name, ad_group.status, ad_group.type, ad_group.cpc_bid_micros, ad_group.tracking_url_template, ad_group.final_url_suffix FROM ad_group WHERE ad_group.id = {ad_group} AND campaign.id = {campaign} LIMIT 2", 2),
    ("keywords", "SELECT ad_group.id, ad_group_criterion.criterion_id, ad_group_criterion.status, ad_group_criterion.negative, ad_group_criterion.keyword.text, ad_group_criterion.keyword.match_type, ad_group_criterion.cpc_bid_micros FROM ad_group_criterion WHERE ad_group.id = {ad_group} AND ad_group_criterion.type = 'KEYWORD' AND ad_group_criterion.status != 'REMOVED' LIMIT 200", 200),
    ("ads", "SELECT ad_group.id, ad_group_ad.ad.id, ad_group_ad.ad.type, ad_group_ad.ad.final_urls, ad_group_ad.ad.tracking_url_template, ad_group_ad.ad.responsive_search_ad.headlines, ad_group_ad.ad.responsive_search_ad.descriptions, ad_group_ad.ad.responsive_search_ad.path1, ad_group_ad.ad.responsive_search_ad.path2, ad_group_ad.status FROM ad_group_ad WHERE ad_group.id = {ad_group} AND ad_group_ad.status != 'REMOVED' LIMIT 100", 100),
    ("campaign_targeting", "SELECT campaign.id, campaign_criterion.criterion_id, campaign_criterion.type, campaign_criterion.status, campaign_criterion.negative, campaign_criterion.location.geo_target_constant, campaign_criterion.language.language_constant, campaign_criterion.keyword.text, campaign_criterion.keyword.match_type, campaign_criterion.ad_schedule.day_of_week, campaign_criterion.ad_schedule.start_hour, campaign_criterion.ad_schedule.end_hour FROM campaign_criterion WHERE campaign.id = {campaign} AND campaign_criterion.status != 'REMOVED' LIMIT 200", 200),
    ("ad_group_targeting", "SELECT ad_group.id, ad_group_criterion.criterion_id, ad_group_criterion.type, ad_group_criterion.status, ad_group_criterion.negative FROM ad_group_criterion WHERE ad_group.id = {ad_group} AND ad_group_criterion.type != 'KEYWORD' AND ad_group_criterion.status != 'REMOVED' LIMIT 100", 100),
    ("shared_sets", "SELECT campaign.id, campaign_shared_set.shared_set, campaign_shared_set.status FROM campaign_shared_set WHERE campaign.id = {campaign} AND campaign_shared_set.status != 'REMOVED' LIMIT 100", 100),
    ("campaign_assets", "SELECT campaign.id, campaign_asset.asset, campaign_asset.field_type, campaign_asset.status FROM campaign_asset WHERE campaign.id = {campaign} AND campaign_asset.status != 'REMOVED' LIMIT 100", 100),
    ("ad_group_assets", "SELECT ad_group.id, ad_group_asset.asset, ad_group_asset.field_type, ad_group_asset.status FROM ad_group_asset WHERE ad_group.id = {ad_group} AND ad_group_asset.status != 'REMOVED' LIMIT 100", 100),
)


def audit_crm_migration(tenant: str, customer_id: str, campaign_id: str, ad_group_id: str, manager_id=None) -> dict:
    from app.core.google_ads_gateway import _customer_id, _read

    cid = _customer_id(customer_id)
    campaign = str(campaign_id or "").strip()
    group = str(ad_group_id or "").strip()
    if not campaign.isascii() or not group.isascii() or not campaign.isdecimal() or not group.isdecimal():
        raise HTTPException(422, "campaign_id and ad_group_id must be numeric.")
    if not (1 <= len(campaign) <= 20 and 1 <= len(group) <= 20):
        raise HTTPException(422, "Invalid campaign or ad group ID.")
    mid = _customer_id(manager_id) if manager_id else None
    sections = {}
    failed = []
    truncated = []
    for name, template, size in SECTIONS:
        q = template.format(campaign=campaign, ad_group=group)
        try:
            data = _read(q, tenant, cid, mid, limit=size)
            rows = data.get("rows") or []
            sections[name] = {
                "ok": True, "count": len(rows),
                "truncated": bool(data.get("truncated")),
                "rows": rows,
            }
            if data.get("truncated"):
                truncated.append(name)
        except HTTPException as exc:
            safe = _safe_google_ads_error(exc)
            sections[name] = {"ok": False, "error": safe}
            failed.append(name)

    identity_ok = False
    campaign_rows = sections.get("campaign", {}).get("rows") or []
    group_rows = sections.get("ad_group", {}).get("rows") or []
    if campaign_rows and group_rows:
        actual_campaign = str((campaign_rows[0].get("campaign") or {}).get("id") or "")
        actual_group = str((group_rows[0].get("adGroup") or {}).get("id") or "")
        actual_parent = str((group_rows[0].get("campaign") or {}).get("id") or "")
        identity_ok = actual_campaign == campaign and actual_group == group and actual_parent == campaign

    complete = identity_ok and not failed and not truncated
    return {
        "ok": complete,
        "provider": "google_ads", "action": "audit_crm_migration",
        "mode": "READ_ONLY", "no_changes_applied": True,
        "customer_id": cid, "campaign_id": campaign, "ad_group_id": group,
        "identity_verified": identity_ok,
        "sections": sections, "failed_sections": failed,
        "truncated_sections": truncated,
        "audit_complete": complete,
        "safe_to_clone_automatically": False,
        "review_required": [
            "Check source campaign conversion goals, schedules, bid adjustments, exclusions, assets and account-level inherited settings.",
            "Confirm all active and paused ads and keywords were included, with exact text, match type, negatives, policy status and URLs.",
            "Check campaign-level shared lists, audience/location/language targeting and asset associations.",
            "Review bidding learning reset and attribution differences after creating a separate campaign.",
            "Review combined daily budgets: old campaign 500 EGP plus proposed new campaign 800 EGP.",
            "Only pause the original crm group after new campaign and tracking are validated and user explicitly approves.",
        ],
        "next_step": (
            "Resolve failed_sections or truncated_sections; do not clone."
            if not complete else
            "Review each section and create a human-approved migration plan; this audit does not authorize mutation."
        ),
    }
