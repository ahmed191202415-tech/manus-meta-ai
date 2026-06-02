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

    assert result == {"ok": True, "path": "120246445412420505/insights", "data": {"data": []}}
    assert calls == [
        (
            "GET",
            "120246445412420505/insights",
            "user_token",
            {"date_preset": "today", "fields": "spend,impressions"},
        )
    ]


def test_meta_query_returns_graph_error_as_data(monkeypatch):
    monkeypatch.setattr(
        meta_raw,
        "meta_call",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            meta_raw.HTTPException(status_code=400, detail={"message": "Invalid field", "code": 100})
        ),
    )

    result = asyncio.run(
        meta_raw.read_only_meta_query(
            ReadOnlyMetaQueryRequest(path="120246445412420505/insights"),
            token="user_token",
        )
    )

    assert result["ok"] is False
    assert result["error"] == {"message": "Invalid field", "code": 100}


def test_meta_query_uses_routed_token_for_page_reads(monkeypatch):
    calls = []
    monkeypatch.setattr(meta_raw, "choose_token_for_meta_path", lambda **kwargs: "page_token")
    monkeypatch.setattr(
        meta_raw,
        "meta_call",
        lambda method, path, token, params=None: calls.append((method, path, token, params)) or {"data": []},
    )

    result = asyncio.run(
        meta_raw.read_only_meta_query(
            ReadOnlyMetaQueryRequest(path="487462921107773/posts", params={"fields": "id,message"}),
            token="user_token",
        )
    )

    assert result["ok"] is True
    assert calls == [("GET", "487462921107773/posts", "page_token", {"fields": "id,message"})]
