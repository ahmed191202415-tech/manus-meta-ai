import asyncio

from app.api import meta_raw
from app.schemas.meta_requests import SmartMetaInsightsRequest


def test_smart_insights_uses_direct_campaign_path(monkeypatch):
    calls = []

    def meta_call(method, path, token, params=None):
        calls.append((method, path, token, dict(params or {})))
        if path.endswith("/insights"):
            return {"data": [{"campaign_id": "10", "spend": "12.50"}]}
        return {"id": "10", "name": "Campaign"}

    monkeypatch.setattr(meta_raw, "meta_call", meta_call)

    result = asyncio.run(
        meta_raw.smart_meta_insights(
            SmartMetaInsightsRequest(account_id="123", campaign_id="10", date_preset="today"),
            token="token",
        )
    )

    assert result["ok"] is True
    assert result["path"] == "10/insights"
    assert result["scope"] == {"type": "campaign", "id": "10", "level": "campaign", "account_id": "act_123"}
    assert calls[0][1] == "10/insights"


def test_smart_insights_resolves_named_account(monkeypatch):
    def meta_call(method, path, token, params=None):
        if path == "me/adaccounts":
            return {"data": [{"id": "act_123", "name": "BeOn"}, {"id": "act_456", "name": "Other"}]}
        return {"data": []}

    monkeypatch.setattr(meta_raw, "meta_call", meta_call)

    result = asyncio.run(
        meta_raw.smart_meta_insights(
            SmartMetaInsightsRequest(account_name="beon", date_preset="today"),
            token="token",
        )
    )

    assert result["ok"] is True
    assert result["path"] == "act_123/insights"


def test_smart_insights_uses_minimal_fields_once_when_standard_fields_fail(monkeypatch):
    calls = []

    def meta_call(method, path, token, params=None):
        calls.append((path, dict(params or {})))
        if path == "10/insights" and params.get("fields") == meta_raw.SMART_INSIGHTS_FIELDS:
            raise meta_raw.HTTPException(status_code=400, detail={"message": "Invalid field", "code": 100})
        if path == "10/insights":
            return {"data": [{"campaign_id": "10", "spend": "2"}]}
        return {"id": "10", "name": "Campaign"}

    monkeypatch.setattr(meta_raw, "meta_call", meta_call)

    result = asyncio.run(
        meta_raw.smart_meta_insights(
            SmartMetaInsightsRequest(account_id="123", campaign_id="10"),
            token="token",
        )
    )

    assert result["ok"] is True
    assert result["fields_mode"] == "minimal_fallback"
    assert result["warnings"][0]["type"] == "standard_fields_rejected"
    assert len([path for path, _ in calls if path == "10/insights"]) == 2


def test_smart_insights_keeps_pixel_limits_separate_from_campaign_data(monkeypatch):
    monkeypatch.setattr(
        meta_raw,
        "meta_call",
        lambda method, path, token, params=None: (
            {"data": [{"campaign_id": "10"}]} if path == "10/insights" else {"id": "10", "name": "Campaign"}
        ),
    )

    result = asyncio.run(
        meta_raw.smart_meta_insights(
            SmartMetaInsightsRequest(account_id="123", campaign_id="10"),
            token="token",
        )
    )

    assert result["ok"] is True
    assert "Pixel" in result["permission_note"]
