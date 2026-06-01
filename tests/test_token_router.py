from fastapi import HTTPException

from app.core import token_router


def test_resolve_page_token_uses_saved_selected_page_token(monkeypatch):
    monkeypatch.setattr(
        token_router,
        "find_meta_connection_by_access_token",
        lambda token: {"selected_page_id": "page_1", "selected_page_access_token": "saved_page_token"},
    )
    monkeypatch.setattr(token_router, "_list_page_entries", lambda token: (_ for _ in ()).throw(AssertionError("must use saved token")))

    assert token_router.resolve_page_token_for_page_id("user_token", "page_1") == "saved_page_token"


def test_resolve_page_token_fetches_page_token_from_managed_pages(monkeypatch):
    monkeypatch.setattr(token_router, "find_meta_connection_by_access_token", lambda token: None)
    monkeypatch.setattr(
        token_router,
        "_list_page_entries",
        lambda token: [{"id": "page_1", "name": "BeOn", "access_token": "fetched_page_token"}],
    )

    assert token_router.resolve_page_token_for_page_id("user_token", "page_1") == "fetched_page_token"


def test_resolve_page_token_rejects_user_token_fallback(monkeypatch):
    monkeypatch.setattr(token_router, "find_meta_connection_by_access_token", lambda token: None)
    monkeypatch.setattr(token_router, "_list_page_entries", lambda token: [])

    try:
        token_router.resolve_page_token_for_page_id("user_token", "page_1")
    except HTTPException as exc:
        assert exc.status_code == 403
        assert "No Page access token" in str(exc.detail)
    else:
        raise AssertionError("Expected a clear Page token error.")
