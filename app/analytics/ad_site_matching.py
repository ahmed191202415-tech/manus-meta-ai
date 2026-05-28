def build_ad_site_matching(meta_rows: list[dict], ga4_rows: list[dict]) -> dict:
    matched_on = []
    limits = []
    confidence = "unavailable"

    ga_campaigns = {str(row.get("sessionCampaignName") or "").lower() for row in ga4_rows}
    meta_campaigns = {str(row.get("campaign_name") or "").lower() for row in meta_rows}
    if meta_campaigns and ga_campaigns and meta_campaigns.intersection(ga_campaigns):
        matched_on.append("campaign_name")
        confidence = "medium"

    source_mediums = {str(row.get("sessionSourceMedium") or "").lower() for row in ga4_rows}
    if any("facebook" in item or "instagram" in item or "meta" in item for item in source_mediums):
        matched_on.append("source_medium")
        confidence = "medium" if confidence != "medium" else "medium"

    if confidence == "unavailable":
        limits.append("No reliable campaign or source match found between Meta and GA4")
    if "campaign_name" not in matched_on:
        limits.append("No campaign name match found")
    limits.append("No ad_id custom dimension was found in GA4, so ad-level conclusions are limited")

    return {
        "matching_confidence": confidence,
        "matched_on": matched_on,
        "limits": limits,
    }
