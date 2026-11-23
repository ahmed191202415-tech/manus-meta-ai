"""Prevent Meta provider failure from starting repeated ChatGPT OAuth sign-ins."""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core import auth


def request_for(bearer):
    return SimpleNamespace(
        session={},
        headers={"authorization": "Bearer " + bearer},
        query_params={},
    )


def test_valid_gpt_token_without_meta_does_not_trigger_signin(monkeypatch):
    monkeypatch.setattr(auth, "_safe_get_app_token_data", lambda bearer: {
        "tenant_id": "tenant", "meta_access_token": None, "meta_user_id": "__gpt_google_identity__"
    })
    monkeypatch.setattr(auth, "_safe_find_meta_connection_by_access_token",
                        lambda bearer: pytest.fail("Must not treat GPT bearer as Meta token"))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(auth.resolve_access_token(request_for("app_valid")))
    assert exc.value.status_code == 409


def test_expired_gpt_token_requires_signin(monkeypatch):
    monkeypatch.setattr(auth, "_safe_get_app_token_data", lambda bearer: None)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(auth.resolve_access_token(request_for("app_expired")))
    assert exc.value.status_code == 401


def test_invalid_meta_token_does_not_purge_customer_connection(monkeypatch):
    req = request_for("app_valid")
    monkeypatch.setattr(auth, "_validate_meta_access_token",
                        lambda *args, **kw: (_ for _ in ()).throw(
                            HTTPException(400, {"code": 190, "message": "Invalid OAuth access token"})
                        ))
    monkeypatch.setattr(auth, "purge_meta_connection",
                        lambda *args, **kw: pytest.fail("Must not delete shared Meta connection"))
    with pytest.raises(HTTPException) as exc:
        auth._resolve_valid_saved_token(req, "bad-meta-token", "123", "tenant")
    assert exc.value.status_code == 409


def test_meta_identity_mismatch_not_401_or_purged(monkeypatch):
    req = request_for("app_valid")
    monkeypatch.setattr(auth, "_validate_meta_access_token",
                        lambda *args, **kw: {"id": "other"})
    monkeypatch.setattr(auth, "purge_meta_connection",
                        lambda *args, **kw: pytest.fail("Must not delete shared Meta connection"))
    with pytest.raises(HTTPException) as exc:
        auth._resolve_valid_saved_token(req, "meta-token", "expected", "tenant")
    assert exc.value.status_code == 409


def test_valid_meta_token_still_works(monkeypatch):
    monkeypatch.setattr(auth, "_validate_meta_access_token",
                        lambda *args, **kw: {"id": "expected"})
    assert auth._resolve_valid_saved_token(request_for("app_valid"), "meta-token", "expected", "tenant") == "meta-token"
