from app.api.journey import _filter_meta_payload_rows, _normalize_meta_payload_rows
from app.schemas.ga4_requests import JourneyPayloadAnalysisRequest


def test_normalize_meta_payload_rows_supports_nested_mcp_shapes():
    rows = _normalize_meta_payload_rows([
        {
            "id": "120",
            "name": "Ad name",
            "campaign": {"id": "10", "name": "Campaign name"},
            "adset": {"id": "20", "name": "Ad set name"},
        }
    ])

    assert rows[0]["campaign_id"] == "10"
    assert rows[0]["campaign_name"] == "Campaign name"
    assert rows[0]["adset_id"] == "20"
    assert rows[0]["adset_name"] == "Ad set name"
    assert rows[0]["ad_id"] == "120"
    assert rows[0]["ad_name"] == "Ad name"


def test_filter_meta_payload_rows_uses_campaign_and_ad_filters():
    body = JourneyPayloadAnalysisRequest(campaign_id="10", ad_id="120")
    rows = _filter_meta_payload_rows(
        [
            {"campaign_id": "10", "ad_id": "120"},
            {"campaign_id": "10", "ad_id": "121"},
            {"campaign_id": "11", "ad_id": "120"},
        ],
        body,
    )

    assert rows == [{"campaign_id": "10", "ad_id": "120"}]
