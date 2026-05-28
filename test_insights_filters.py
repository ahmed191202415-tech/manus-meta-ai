from app.api.insights import _build_insights_filters, _local_filter_rows


def test_build_insights_filters_accepts_simple_campaign_id():
    filters = _build_insights_filters(None, "123", None, None, None)
    assert filters == [{"field": "campaign.id", "operator": "IN", "value": ["123"]}]


def test_local_filter_rows_by_campaign_name():
    rows = [
        {"campaign_id": "1", "campaign_name": "Test Campaign"},
        {"campaign_id": "2", "campaign_name": "Other"},
    ]
    result = _local_filter_rows(rows, None, "test", None, None)
    assert result == [rows[0]]
