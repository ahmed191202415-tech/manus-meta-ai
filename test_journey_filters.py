from app.api.journey import _build_matched_entities, _filter_meta_creative_rows, _ga4_filter_limits, _resolve_meta_level
from app.schemas.ga4_requests import JourneyAnalysisRequest


def test_journey_filter_resolves_ad_level_from_ad_id():
    body = JourneyAnalysisRequest(meta_account_id="act_1", ad_id="ad_1")
    assert _resolve_meta_level(body) == "ad"
    assert "ad_id" in _ga4_filter_limits(body)[0]


def test_journey_filters_creative_rows_by_adset_and_ad():
    body = JourneyAnalysisRequest(meta_account_id="act_1", adset_id="set_1", ad_id="ad_1")
    rows = [
        {"id": "ad_1", "adset_id": "set_1"},
        {"id": "ad_2", "adset_id": "set_1"},
        {"id": "ad_1", "adset_id": "set_2"},
    ]
    assert _filter_meta_creative_rows(rows, body) == [rows[0]]


def test_journey_builds_named_matched_entities_from_manual_ad_content():
    result = _build_matched_entities(
        [],
        [{"id": "ad_1", "name": "Winning Ad", "campaign_id": "camp_1", "campaign_name": "Campaign", "adset_id": "set_1", "adset_name": "Ad Set"}],
        [{"sessionManualAdContent": "ad_1", "sessions": 12, "activeUsers": 8, "engagedSessions": 4}],
    )
    assert result["ads"][0]["ad_name"] == "Winning Ad"
    assert result["ads"][0]["campaign_name"] == "Campaign"
    assert result["ads"][0]["ga4_metrics"]["sessions"] == 12
