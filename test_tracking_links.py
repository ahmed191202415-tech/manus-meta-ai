from app.analytics.tracking_links import audit_meta_tracking_links


def test_tracking_link_audit_scores_complete_utm_and_matching_page():
    result = audit_meta_tracking_links(
        [
            {
                "id": "ad_1",
                "name": "Ad 1",
                "creative": {
                    "url_tags": "utm_source=facebook&utm_medium=paid&utm_campaign=spring&ad_id=ad_1",
                    "object_story_spec": {"link_data": {"link": "https://example.com/pricing"}},
                },
            }
        ],
        [{"landingPagePlusQueryString": "/pricing", "sessions": 10}],
    )
    assert result["tracking_link_score"] == 100
    assert result["utm_complete_links"] == 1
    assert result["strong_id_links"] == 1
