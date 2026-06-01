import asyncio

from app.api import creatives


def test_creative_list_uses_lightweight_fields_by_default(monkeypatch):
    calls = []
    monkeypatch.setattr(
        creatives,
        "meta_call",
        lambda method, path, token, params=None, data=None: calls.append((method, path, params)) or {"data": []},
    )

    asyncio.run(creatives.list_adcreatives(account_id="123", token="token"))

    assert calls[0][1] == "act_123/adcreatives"
    assert "asset_feed_spec" not in calls[0][2]["fields"]
    assert "object_story_spec" not in calls[0][2]["fields"]


def test_creative_details_load_one_requested_creative(monkeypatch):
    calls = []
    monkeypatch.setattr(
        creatives,
        "meta_call",
        lambda method, path, token, params=None, data=None: calls.append((method, path, params)) or {"id": path},
    )

    asyncio.run(creatives.list_adcreatives(account_id="123", creative_id="creative_1", include_details=True, token="token"))

    assert calls[0][1] == "creative_1"
    assert "asset_feed_spec" in calls[0][2]["fields"]
