from app.analytics.journey_metrics import build_journey_metrics


def test_journey_metrics_do_not_mix_meta_and_ga4_totals():
    result = build_journey_metrics(
        [{"inline_link_clicks": 100, "outbound_clicks": [{"value": "80"}], "actions": [{"action_type": "lead", "value": "5"}]}],
        {"sessions": 40, "engaged_sessions": 20, "conversions": 2},
    )
    assert result["meta_clicks"] == 100
    assert result["ga4_sessions"] == 40
    assert result["meta_pixel_leads"] == 5
    assert result["ga4_conversions"] == 2
