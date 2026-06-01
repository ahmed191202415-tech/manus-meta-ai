import pytest
from fastapi import HTTPException

from app.api import comment_automations


def test_resolve_managed_page_returns_page_token(monkeypatch):
    monkeypatch.setattr(
        comment_automations,
        "meta_call",
        lambda *args, **kwargs: {"data": [{"id": "page_1", "name": "BeOn", "access_token": "page_token"}]},
    )

    page, token = comment_automations._resolve_managed_page("page_1", "user_token")

    assert page["name"] == "BeOn"
    assert token == "page_token"


def test_resolve_managed_page_rejects_post_or_unknown_id(monkeypatch):
    monkeypatch.setattr(
        comment_automations,
        "meta_call",
        lambda *args, **kwargs: {"data": [{"id": "page_1", "name": "BeOn", "access_token": "page_token"}]},
    )

    with pytest.raises(HTTPException) as exc_info:
        comment_automations._resolve_managed_page("post_1", "user_token")

    assert exc_info.value.status_code == 403
    assert "Do not use a post ID" in exc_info.value.detail["next_step"]


def test_subscribe_page_wraps_meta_error_with_operation_context(monkeypatch):
    def fail(*args, **kwargs):
        raise HTTPException(status_code=400, detail={"code": 100, "error_subcode": 33})

    monkeypatch.setattr(comment_automations, "meta_call", fail)

    with pytest.raises(HTTPException) as exc_info:
        comment_automations._subscribe_page("page_1", "page_token")

    assert exc_info.value.detail["operation"] == "subscribe_page_webhook"
    assert exc_info.value.detail["required_permission"] == "pages_manage_metadata"


def test_page_preflight_reports_visible_page_and_missing_permission(monkeypatch):
    def meta_call(method, path, token, params=None):
        if path == "me/accounts":
            return {"data": [{"id": "page_1", "name": "BeOn", "access_token": "page_token"}]}
        if path == "me/permissions":
            return {
                "data": [
                    {"permission": "pages_show_list", "status": "granted"},
                    {"permission": "pages_read_engagement", "status": "granted"},
                ]
            }
        raise AssertionError(path)

    monkeypatch.setattr(comment_automations, "meta_call", meta_call)

    result = comment_automations._page_preflight("page_1", "user_token")

    assert result["page_visible"] is True
    assert result["page_token_available"] is True
    assert result["visible_pages"] == [{"id": "page_1", "name": "BeOn"}]
    assert result["missing_required_permissions"] == ["pages_manage_metadata"]


def test_page_preflight_reports_unknown_page_without_failing(monkeypatch):
    def meta_call(method, path, token, params=None):
        if path == "me/accounts":
            return {"data": [{"id": "page_1", "name": "BeOn", "access_token": "page_token"}]}
        if path == "me/permissions":
            return {"data": []}
        raise AssertionError(path)

    monkeypatch.setattr(comment_automations, "meta_call", meta_call)

    result = comment_automations._page_preflight("wrong_id", "user_token")

    assert result["page_visible"] is False
    assert result["page_token_available"] is False
