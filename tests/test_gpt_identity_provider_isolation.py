"""Valid application identity survives a missing provider, never expiry/revocation."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core import auth, oauth_store as store


NOW = datetime(2026, 11, 22, 18, tzinfo=timezone.utc)


def setup_identity(monkeypatch, *, token_overrides=None, account_overrides=None):
    row = {"tenant_id": "tenant-a", "meta_user_id": "legacy-meta-user", "expires_at": (NOW + timedelta(hours=1)).isoformat(), **(token_overrides or {})}
    account = {"tenant_id": "tenant-a", "status": "active", "access_expires_at": (NOW + timedelta(days=365)).isoformat(), **(account_overrides or {})}
    monkeypatch.setattr(store, "_now_utc", lambda: NOW)
    monkeypatch.setattr(store, "_get_single", lambda *a, **k: row)
    monkeypatch.setattr(store, "get_tenant_account_by_id", lambda tenant: account)
    return row, account


def test_google_identity_survives_missing_legacy_meta_connection(monkeypatch):
    setup_identity(monkeypatch)
    monkeypatch.setattr(store, "get_meta_connection", lambda user, tenant_id: None)
    result = store.get_app_token_data("app_valid")
    assert result == {"tenant_id": "tenant-a", "meta_user_id": "legacy-meta-user", "meta_access_token": None}
    monkeypatch.setattr(auth, "_safe_get_app_token_data", lambda bearer: result)
    request = SimpleNamespace(session={}, query_params={}, headers={"authorization": "Bearer app_valid"})
    with pytest.raises(HTTPException) as caught:
        asyncio.run(auth.resolve_access_token(request))
    assert caught.value.status_code == 409


@pytest.mark.parametrize("account", [
    {"status": "disabled"}, {"status": "deleted"}, {"status": "inactive"},
    {"status": None}, {"deleted_at": NOW.isoformat()}, {"disabled_at": NOW.isoformat()},
    {"access_expires_at": (NOW - timedelta(seconds=1)).isoformat()},
])
def test_tenant_access_checks_still_apply_before_provider_lookup(monkeypatch, account):
    setup_identity(monkeypatch, account_overrides=account)
    monkeypatch.setattr(store, "get_meta_connection", lambda *a, **k: pytest.fail("Denied tenant must not resolve providers"))
    assert store.get_app_token_data("app_valid") is None


@pytest.mark.parametrize("expiry", [
    (NOW - timedelta(seconds=1)).isoformat(), NOW.isoformat(), None, "not-a-date", "2026-11-23T18:00:00",
])
def test_expired_or_malformed_app_tokens_are_rejected(monkeypatch, expiry):
    setup_identity(monkeypatch, token_overrides={"expires_at": expiry})
    monkeypatch.setattr(store, "get_meta_connection", lambda *a, **k: pytest.fail("Invalid token must not resolve providers"))
    assert store.get_app_token_data("app_expired") is None


def test_existing_meta_connection_keeps_same_token_and_tenant_scope(monkeypatch):
    setup_identity(monkeypatch)
    calls = []
    def connection(user, tenant_id):
        calls.append((user, tenant_id))
        return {"meta_access_token": "tenant-meta-token", "meta_user_id": user, "meta_user_name": "Test", "connection_mode": "manual_token"}
    monkeypatch.setattr(store, "get_meta_connection", connection)
    monkeypatch.setattr(store, "get_tenant_meta_app", lambda tenant: None)
    result = store.get_app_token_data("app_valid")
    assert calls == [("legacy-meta-user", "tenant-a")]
    assert result["meta_access_token"] == "tenant-meta-token"
    assert result["tenant_id"] == "tenant-a"
