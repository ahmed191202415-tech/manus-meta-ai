import asyncio

from app.api import pixels
from app.schemas.meta_requests import PixelEventCatalogRequest


def test_normalize_pixel_event_counts_supports_nested_meta_stats_rows():
    rows = [
        {
            "start_time": "2026-06-02T00:00:00+0000",
            "aggregation": "event_total_counts",
            "data": [
                {"event": "PageView", "count": 12},
                {"event_name": "Lead", "value": "3"},
                ["Purchase", 2],
            ],
        }
    ]

    assert pixels._normalize_pixel_event_counts(rows) == [
        {"event_name": "PageView", "count": 12},
        {"event_name": "Lead", "count": 3},
        {"event_name": "Purchase", "count": 2},
    ]


def test_pixel_event_catalog_expands_empty_single_day_range(monkeypatch):
    calls = []

    def fake_meta_call(method, path, token, params=None):
        calls.append((method, path, token, params))
        if len(calls) == 1:
            return {"data": [{"aggregation": "event_total_counts", "data": []}]}
        return {"data": [{"aggregation": "event_total_counts", "data": [{"event": "PageView", "count": 5}]}]}

    monkeypatch.setattr(pixels, "meta_call", fake_meta_call)
    result = asyncio.run(
        pixels.pixel_event_catalog(
            PixelEventCatalogRequest(
                pixel_id="2025821897925927",
                start_date="2026-06-02",
                end_date="2026-06-02",
            ),
            token="user_token",
        )
    )

    assert result["event_names"] == ["PageView"]
    assert result["fallback_used"] is True
    assert result["attempts"][0] == {
        "start_date": "2026-06-02",
        "end_date": "2026-06-02",
        "raw_row_count": 1,
        "named_event_count": 0,
    }
    assert calls[0][3]["end_time"] == "2026-06-03"
    assert calls[1][3]["start_time"] == "2026-05-06"


def test_pixel_event_catalog_returns_explicit_limit_when_meta_has_no_named_events(monkeypatch):
    monkeypatch.setattr(
        pixels,
        "meta_call",
        lambda *args, **kwargs: {"data": [{"aggregation": "event_total_counts"}]},
    )

    result = asyncio.run(
        pixels.pixel_event_catalog(
            PixelEventCatalogRequest(pixel_id="2025821897925927"),
            token="user_token",
        )
    )

    assert result["event_names"] == []
    assert "Custom Conversions are configuration objects" in result["limits"][1]
