import asyncio

from app.api import meta_raw
from app.schemas.meta_requests import RawMetaRequest, ReadOnlyMetaQueryRequest


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


def test_meta_write_passes_explicit_page_id_to_token_router(monkeypatch):
    routing_calls = []
    graph_calls = []
    monkeypatch.setattr(
        meta_raw,
        "choose_token_for_meta_path",
        lambda **kwargs: routing_calls.append(kwargs) or "page_token",
    )
    monkeypatch.setattr(
        meta_raw,
        "meta_call",
        lambda method, path, token, params=None, data=None: graph_calls.append((method, path, token, params, data)) or {"id": "reply_1"},
    )

    result = asyncio.run(
        meta_raw.raw_meta_request(
            RawMetaRequest(
                method="POST",
                path="comment_1/comments",
                page_id="page_1",
                data={"message": "Thanks"},
            ),
            token="user_token",
        )
    )

    assert result == {"id": "reply_1"}
    assert routing_calls[0]["page_id"] == "page_1"
    assert graph_calls == [("POST", "comment_1/comments", "page_token", {}, {"message": "Thanks"})]


def test_meta_write_clones_existing_engagement_audience_rule(monkeypatch):
    calls = []

    def fake_meta_call(method, path, token, params=None, data=None):
        calls.append((method, path, token, params, data))
        if method == "GET":
            return {
                "id": "120247050271910505",
                "name": "Warm Page Contact Signals - BeOn 365d",
                "subtype": "CUSTOM",
                "retention_days": 365,
                "rule": {
                    "inclusions": {
                        "operator": "or",
                        "rules": [
                            {
                                "event_sources": [{"id": "487462921107773", "type": "page"}],
                                "retention_seconds": 31536000,
                                "filter": {"event": {"eq": "page_engaged"}},
                            }
                        ],
                    }
                },
            }
        return {"id": "new_audience_1"}

    monkeypatch.setattr(meta_raw, "meta_call", fake_meta_call)

    result = asyncio.run(
        meta_raw.raw_meta_request(
            RawMetaRequest(
                method="POST",
                path="act_763606732391242/customaudiences",
                source_audience_id="120247050271910505",
                audience_retention_days=30,
                data={
                    "name": "BeOn_All_Meta_Engagers_30D_Exclude_Frequency",
                    "subtype": "CUSTOM",
                    "customer_file_source": "USER_PROVIDED_ONLY",
                },
            ),
            token="user_token",
        )
    )

    assert result["ok"] is True
    assert result["audience"]["id"] == "new_audience_1"
    payload = calls[1][4]
    assert payload["retention_days"] == 30
    assert payload["prefill"] is True
    assert "customer_file_source" not in payload
    assert payload["rule"]["inclusions"]["rules"][0]["retention_seconds"] == 2592000


def test_meta_write_returns_exact_error_when_cloned_rule_is_rejected(monkeypatch):
    def fake_meta_call(method, path, token, params=None, data=None):
        if method == "GET":
            return {
                "id": "source_1",
                "name": "Working engagement audience",
                "subtype": "CUSTOM",
                "rule": {"retention_seconds": 31536000, "event": "page_engaged"},
            }
        raise meta_raw.HTTPException(
            status_code=400,
            detail={"message": "Invalid rule", "code": 100, "error_subcode": 1885364},
        )

    monkeypatch.setattr(meta_raw, "meta_call", fake_meta_call)

    result = asyncio.run(
        meta_raw.raw_meta_request(
            RawMetaRequest(
                method="POST",
                path="act_1/customaudiences",
                source_audience_id="source_1",
                audience_retention_days=30,
                data={"name": "New 30d audience"},
            ),
            token="user_token",
        )
    )

    assert result["ok"] is False
    assert result["error"]["message"] == "Invalid rule"
    assert result["error"]["error_subcode"] == 1885364
    assert result["payload_sent"]["rule"]["retention_seconds"] == 2592000
