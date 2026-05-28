from app.analytics.ad_site_matching import build_ad_site_matching


def test_ad_site_matching_campaign_name_medium_confidence():
    result = build_ad_site_matching(
        [{"campaign_name": "Summer Sale"}],
        [{"sessionCampaignName": "summer sale", "sessionSourceMedium": "facebook / paid"}],
    )
    assert result["matching_confidence"] == "medium"
    assert "campaign_name" in result["matched_on"]
