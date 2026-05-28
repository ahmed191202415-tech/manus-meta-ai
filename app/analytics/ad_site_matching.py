def build_ad_site_matching(meta_rows: list[dict], ga4_rows: list[dict], link_audit: dict | None = None) -> dict:
    matched_on = []
    limits = []
    confidence = "unavailable"
    link_audit = link_audit or {}

    if link_audit.get("strong_id_links"):
        matched_on.append("ad_or_campaign_id")
        confidence = "high"

    if link_audit.get("matched_landing_pages"):
        matched_on.append("landing_page")
        confidence = "medium" if confidence == "unavailable" else confidence

    ga_campaigns = {str(row.get("sessionCampaignName") or "").lower() for row in ga4_rows}
    meta_campaigns = {str(row.get("campaign_name") or "").lower() for row in meta_rows}
    if meta_campaigns and ga_campaigns and meta_campaigns.intersection(ga_campaigns):
        matched_on.append("campaign_name")
        confidence = "medium" if confidence == "unavailable" else confidence

    source_mediums = {str(row.get("sessionSourceMedium") or "").lower() for row in ga4_rows}
    if any("facebook" in item or "instagram" in item or "meta" in item for item in source_mediums):
        matched_on.append("source_medium")
        confidence = "low" if confidence == "unavailable" else confidence

    if confidence == "unavailable":
        limits.append("No reliable campaign or source match found between Meta and GA4")
    if "campaign_name" not in matched_on:
        limits.append("No campaign name match found")
    if "ad_or_campaign_id" not in matched_on:
        limits.append("No ad_id or campaign_id was found in Meta URL tracking, so ad-level conclusions are limited")

    return {
        "matching_confidence": confidence,
        "matched_on": matched_on,
        "limits": limits,
        "tracking_link_score": link_audit.get("tracking_link_score"),
    }
