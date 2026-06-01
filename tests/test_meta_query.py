import asyncio

from app.api import meta_raw
from app.schemas.meta_requests import ReadOnlyMetaQueryRequest


def test_meta_query_is_read_only_get(monkeypatch):
    calls = []
    monkeypatch.setattr(
        meta_raw,
        "meta_call",
        lambda method, path, token, params=None: calls.append((method, path, token, params)) or {"data": []},
    )

    result = asyncio.run(
        meta_raw.read_only_meta_query(
            ReadOnlyMetaQueryRequest(
                path="120246445412420505/insights",
                params={"date_preset": "today", "fields": "spend,impressions"},
            ),
            token="user_token",
        )
    )

    assert result == {"data": []}
    assert calls == [
        (
            "GET",
            "120246445412420505/insights",
            "user_token",
            {"date_preset": "today", "fields": "spend,impressions"},
        )
    ]
