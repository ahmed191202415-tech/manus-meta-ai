from app.analytics.clarity_ad_matching import build_clarity_ad_behavior


def test_clarity_ad_behavior_matches_by_campaign_and_landing_url():
    result = build_clarity_ad_behavior(
        {
            "ads": [
                {
                    "campaign_id": "camp_1",
                    "campaign_name": "Campaign One",
                    "adset_id": "set_1",
                    "adset_name": "Set One",
                    "ad_id": "ad_1",
                    "ad_name": "Ad One",
                    "ga4_metrics": {"sessions": 10},
                }
            ]
        },
        {"links": [{"ad_id": "ad_1", "url": "https://example.com/landing"}]},
        [
            {"metricName": "Traffic", "Campaign": "camp_1", "URL": "https://example.com/landing", "Device": "Mobile", "sessionsCount": "7"},
            {"metricName": "DeadClickCount", "Campaign": "camp_1", "URL": "https://example.com/landing", "Device": "Mobile", "sessionsCount": "7", "subTotal": "2"},
        ],
    )
    assert result[0]["ad_name"] == "Ad One"
    assert result[0]["clarity_matched_rows"] == 2
    assert result[0]["clarity_behavior"]["sessions"] == 14
    assert "clarity_campaign" in result[0]["matching_basis"]
