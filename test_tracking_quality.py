from app.analytics.tracking_quality import build_tracking_quality


def test_tracking_quality_flags_missing_conversion_events():
    result = build_tracking_quality(
        connected=True,
        property_selected=True,
        traffic_rows=[{"sessions": 100}],
        landing_page_rows=[{"landingPagePlusQueryString": "/"}],
        event_rows=[{"eventName": "page_view", "eventCount": 100}],
    )
    assert result["level"] in {"medium", "good"}
    assert "generate_lead" in result["missing_events"]
    assert "purchase" in result["missing_events"]
