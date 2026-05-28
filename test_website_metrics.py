from app.analytics.website_metrics import summarize_website_metrics


def test_website_metrics_missing_metrics_are_reported():
    result = summarize_website_metrics(
        traffic_rows=[{"sessions": 100, "activeUsers": 80, "engagedSessions": 50}],
        landing_page_rows=[],
        event_rows=[],
        device_rows=[],
    )
    assert result["sessions"] == 100
    assert result["engagement_rate"] == 0.5
    assert "conversions" in result["missing_metrics"]
