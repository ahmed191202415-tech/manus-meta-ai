import json

from app.core.response_guard import ResponseGuardMiddleware, guard_json_bytes


def _decode(payload: bytes) -> dict:
    return json.loads(payload.decode("utf-8"))


def test_guard_redacts_tokens_and_pagination_urls_even_for_small_responses():
    result = _decode(
        guard_json_bytes(
            json.dumps(
                {
                    "access_token": "secret",
                    "refresh_token": "refresh",
                    "paging": {
                        "next": "https://graph.facebook.com/next?access_token=secret",
                        "cursors": {"after": "cursor_1"},
                    },
                }
            ).encode(),
            max_bytes=350_000,
        )
    )

    assert result["access_token"] == "[redacted]"
    assert result["refresh_token"] == "[redacted]"
    assert result["paging"]["next"] == "[omitted pagination URL; use cursors.after]"
    assert result["paging"]["cursors"]["after"] == "cursor_1"


def test_guard_compacts_large_nested_payload_and_keeps_progressive_hint():
    rows = [
        {
            "id": f"ad_{index}",
            "name": f"Ad {index}",
            "asset_feed_spec": {"bodies": [{"text": "x" * 10_000}] * 5},
            "object_story_spec": {"link_data": {"message": "y" * 10_000}},
        }
        for index in range(200)
    ]

    result_bytes = guard_json_bytes(json.dumps({"data": rows}).encode(), max_bytes=80_000)
    result = _decode(result_bytes)

    assert len(result_bytes) < 80_000
    assert result["_response_guard"]["compacted"] is True
    assert "Request a smaller limit" in result["_response_guard"]["hint"]
    assert result["data"][0]["id"] == "ad_0"
    assert result["data"][0]["asset_feed_spec"]["_omitted"] is True
    assert result["data"][-1]["_truncated_items"] > 0


def test_guard_leaves_small_business_payload_shape_unchanged():
    result = _decode(guard_json_bytes(b'{"data":[{"id":"1","name":"Campaign"}]}', max_bytes=350_000))

    assert result == {"data": [{"id": "1", "name": "Campaign"}]}


def test_middleware_compacts_guarded_fastapi_response():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.add_middleware(ResponseGuardMiddleware, max_bytes=50_000, guarded_paths={"/data"})

    @app.get("/data")
    async def data():
        return {"data": [{"id": str(index), "asset_feed_spec": {"text": "x" * 5000}} for index in range(100)]}

    response = TestClient(app).get("/data")

    assert response.status_code == 200
    assert response.json()["_response_guard"]["compacted"] is True
