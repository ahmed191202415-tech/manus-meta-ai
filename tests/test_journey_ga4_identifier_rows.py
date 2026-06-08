from app.api import journey


def test_ga4_journey_reports_try_campaign_identifier_dimensions(monkeypatch):
    calls = []

    def fake_run_ga4_report(tenant_id, property_id, dimensions, metrics, start_date, end_date, limit):
        calls.append(tuple(dimensions))
        return {"dimensionHeaders": [], "metricHeaders": [], "rows": [], "property_id": property_id}

    monkeypatch.setattr(journey, "run_ga4_report", fake_run_ga4_report)

    journey._ga4_journey_reports("tenant@example.com", "529884683", "30daysAgo", "today", 100)

    assert ("sessionCampaignId", "sessionCampaignName", "sessionSourceMedium") in calls
    assert (
        "sessionManualCampaignId",
        "sessionManualCampaignName",
        "sessionManualAdContent",
        "sessionSourceMedium",
    ) in calls
