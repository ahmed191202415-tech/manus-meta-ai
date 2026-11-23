"""Read-only GPT Actions don't require repeated consequential approval."""
import json
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.main import app, openapi_gpt_schema
from app.api import gpt_tools


def test_read_and_write_openapi_approval_contract():
    schema = openapi_gpt_schema()
    assert schema["paths"]["/tools/read"]["post"]["x-openai-isConsequential"] is False
    for path in ("/meta/query", "/meta/smart_insights", "/tools/ga4", "/tools/clarity"):
        assert schema["paths"][path]["post"]["x-openai-isConsequential"] is False
    for path in ("/tools/intent", "/meta/request", "/comment_automations/manage", "/tools/dashboards"):
        assert schema["paths"][path]["post"]["x-openai-isConsequential"] is True


def test_safe_read_dispatcher_forwards_ordinary_intent(monkeypatch):
    async def fake_intent(body, request):
        return {"ok": True, "intent": "ga4"}
    monkeypatch.setattr(gpt_tools, "intent_tool", fake_intent)
    body = SimpleNamespace(request="analyze GA4 traffic")
    result = asyncio.run(gpt_tools.read_tool(body, object()))
    assert result == {"ok": True, "intent": "ga4"}


@pytest.mark.parametrize("action", ["prepare_mutation", "prepare_negative_keywords", "commit_mutation"])
def test_read_endpoint_blocks_google_ads_writes_before_dispatch(monkeypatch, action):
    async def unexpected(*args):
        pytest.fail("A write reached a read-only endpoint")
    monkeypatch.setattr(gpt_tools, "intent_tool", unexpected)
    payload = {"action": action, "customer_id": "3333735582"}
    body = SimpleNamespace(request="google_ads " + json.dumps(payload))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(gpt_tools.read_tool(body, object()))
    assert exc.value.status_code == 403


def test_exported_schema_not_mutating_main_schema():
    schema = openapi_gpt_schema()
    assert schema["paths"]["/tools/read"]["post"]["x-openai-isConsequential"] is False
    assert "/tools/read" in app.openapi()["paths"]
