"""Keyword inventories disclose their source and reject malformed pagination."""
import pytest
from fastapi import HTTPException

from app.core import google_ads_gateway as gateway
from app.core import google_ads_keyword_inventory as inventory


ARGS = {"customer_id": "3333735582", "campaign_id": "24445941074", "ad_group_id": "55"}


def test_empty_successful_keyword_inventory_has_verified_provenance(monkeypatch):
    calls = []
    monkeypatch.setattr(gateway, "_api", lambda *a, **k: calls.append(1) or {"results": []})
    result = inventory.read_keyword_inventory("tenant-a", ARGS)
    assert len(calls) == 2
    assert result["verified_by_google_api"] is True
    assert result["google_api_called"] is True
    assert result["inventory_complete"] is True
    assert result["count"] == 0


@pytest.mark.parametrize("response", [
    [], {"results": ["malformed"]}, {"results": "malformed"},
    {"nextPageToken": {"unexpected": "object"}}, {"error": {"code": 400}},
])
def test_malformed_keyword_response_is_not_an_empty_success(monkeypatch, response):
    monkeypatch.setattr(gateway, "_api", lambda *a, **k: response)
    with pytest.raises(HTTPException) as caught:
        inventory.read_keyword_inventory("tenant-a", ARGS)
    assert caught.value.status_code == 502


def test_empty_pages_with_unique_tokens_cannot_loop_forever(monkeypatch):
    calls = []
    def empty_page(*args, **kwargs):
        calls.append(1)
        return {"results": [], "nextPageToken": "page-" + str(len(calls))}
    monkeypatch.setattr(gateway, "_api", empty_page)
    with pytest.raises(HTTPException) as caught:
        inventory.read_keyword_inventory("tenant-a", ARGS)
    assert caught.value.status_code == 502
    assert len(calls) == inventory.MAX_KEYWORD_PAGES
