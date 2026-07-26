import asyncio

import pandas as pd

from app.api import analysis, website_analysis
from app.schemas.analysis_requests import AnalysisRunRequest
from app.schemas.ga4_requests import WebsiteAnalysisRequest


def test_analysis_run_summary_kpis_does_not_hit_unbound_response(monkeypatch):
    class Request:
        headers = {"authorization": "Bearer token_1"}
        session = {}

    async def fake_resolve_access_token(request):
        return "token_1"

    monkeypatch.setattr(analysis, "resolve_access_token", fake_resolve_access_token)
    monkeypatch.setattr(
        analysis,
        "fetch_insights_df",
        lambda *args, **kwargs: pd.DataFrame(
            [{"campaign_id": "1", "campaign_name": "Campaign", "spend": 10, "impressions": 100, "clicks": 5}]
        ),
    )
    monkeypatch.setattr(analysis, "fetch_adset_delivery_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(analysis, "save_intelligence_run", lambda *args, **kwargs: "run_1")

    result = asyncio.run(
        analysis.analysis_run(
            AnalysisRunRequest(account_id="act_1", analysis_type="summary_kpis", date_preset="today"),
            Request(),
        )
    )

    assert result["analysis_type"] == "summary_kpis"
    assert "result" in result
    assert "goal_context" in result


def test_website_analysis_returns_partial_data_when_optional_ga4_metrics_fail(monkeypatch):
    class Request:
        headers = {}
        session = {}

    calls = []
    monkeypatch.setattr(website_analysis, "resolve_tenant_id_for_google", lambda request, tenant_id=None: tenant_id or "tenant_1")
    monkeypatch.setattr(website_analysis, "resolve_ga4_property_id", lambda tenant_id, property_id=None: property_id or "529884683")

    def fake_run_ga4_report(tenant_id, property_id, dimensions, metrics, start_date, end_date, limit):
        calls.append(tuple(metrics))
        if "conversions" in metrics:
            raise RuntimeError("Invalid metric: conversions")
        return {
            "dimensionHeaders": [{"name": item} for item in dimensions],
            "metricHeaders": [{"name": item} for item in metrics],
            "rows": [],
        }

    monkeypatch.setattr(website_analysis, "run_ga4_report", fake_run_ga4_report)

    result = asyncio.run(
        website_analysis.website_analyze(
            WebsiteAnalysisRequest(tenant_id="tenant_1", property_id="529884683", start_date="7daysAgo", end_date="today"),
            Request(),
        )
    )

    assert result["partial_data"] is True
    assert result["data_errors"]
    assert any("conversions" in call for call in calls)
    assert any("conversions" not in call for call in calls)
