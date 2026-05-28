from app.api.journey import _filter_meta_creative_rows, _ga4_filter_limits, _resolve_meta_level
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
