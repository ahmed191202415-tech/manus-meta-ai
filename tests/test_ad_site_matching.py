from app.analytics.ad_site_matching import build_ad_site_matching


def test_ad_site_matching_uses_ga4_campaign_id_before_source_medium():
    result = build_ad_site_matching(
        meta_rows=[{"campaign_id": "120246445412420505", "campaign_name": "Test Campaign"}],
        ga4_rows=[
            {
                "sessionCampaignId": "120246445412420505",
                "sessionCampaignName": "anything",
                "sessionSourceMedium": "not set",
                "sessions": 20,
            }
        ],
        link_audit={},
    )

    assert result["matching_confidence"] == "high"
    assert "campaign_id" in result["matched_on"]
    assert result["matched_campaign_ids"] == ["120246445412420505"]


def test_ad_site_matching_uses_manual_campaign_id():
    result = build_ad_site_matching(
        meta_rows=[{"campaign_id": "120246445412420505", "campaign_name": "Test Campaign"}],
        ga4_rows=[{"sessionManualCampaignId": "120246445412420505"}],
        link_audit={},
    )

    assert result["matching_confidence"] == "high"
    assert result["matched_campaign_ids"] == ["120246445412420505"]
