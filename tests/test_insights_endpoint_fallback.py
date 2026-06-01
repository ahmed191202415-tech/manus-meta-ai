import asyncio

from app.api import insights


def test_insights_endpoint_returns_structured_diagnostic_after_all_fallbacks_fail(monkeypatch):
    monkeypatch.setattr(
        insights,
        "fetch_insights_payload",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("ClientResponseError")),
    )

    result = asyncio.run(
        insights.get_insights(
            account_id="1",
            date_preset="today",
            campaign_id="10",
            token="token",
        )
    )

    assert result["available"] is False
    assert result["diagnostic"]["campaign_id"] == "10"
    assert "ClientResponseError" in result["diagnostic"]["error"]


def test_insights_endpoint_uses_progressive_payload_fetcher_by_default(monkeypatch):
    monkeypatch.setattr(
        insights,
        "fetch_insights_payload",
        lambda *args, **kwargs: {"data": [{"campaign_id": "10"}], "fallback_mode": "direct_object_insights"},
    )

    result = asyncio.run(
        insights.get_insights(
            account_id="1",
            date_preset="today",
            campaign_id="10",
            token="token",
        )
    )

    assert result["fallback_mode"] == "direct_object_insights"
    assert result["data"] == [{"campaign_id": "10"}]
