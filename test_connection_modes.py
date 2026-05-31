from unittest.mock import patch

from app.core.connection_resolver import resolve_tenant_connection_state
from app.core.ga4_client import get_google_credentials_for_tenant


def test_manual_meta_token_does_not_require_meta_app_or_secret():
    account = {"tenant_id": "tenant-1", "display_name": "Client", "status": "active"}
    connection = {
        "tenant_id": "tenant-1",
        "meta_user_id": "42",
        "meta_user_name": "Client",
        "meta_access_token": "manual-token",
        "connection_mode": "manual_token",
    }
    with patch("app.core.connection_resolver.get_tenant_account_by_id", return_value=account):
        with patch("app.core.connection_resolver.is_account_expired", return_value=False):
            with patch("app.core.connection_resolver.get_tenant_meta_app", return_value=None):
                with patch("app.core.connection_resolver.get_active_meta_connection_for_tenant", return_value=connection):
                    with patch("app.core.connection_resolver.meta_call", return_value={"id": "42", "name": "Client"}) as meta_call:
                        result = resolve_tenant_connection_state("tenant-1")

    assert result["state"] == "ready"
    assert result["connection"]["connection_mode"] == "manual_token"
    assert meta_call.call_args.kwargs["app_secret"] is None


def test_google_service_account_mode_uses_service_account_refresh():
    connection = {
        "tenant_id": "tenant-1",
        "connection_mode": "service_account",
        "access_token": "old-token",
    }
    refreshed = {
        "connection_mode": "service_account",
        "access_token": "fresh-token",
        "expires_at": "2030-01-01T00:00:00+00:00",
    }
    with patch("app.core.ga4_client.get_google_connection_or_401", return_value=connection):
        with patch("app.core.ga4_client.get_google_service_account_token", return_value=refreshed) as service_refresh:
            with patch("app.core.ga4_client.update_google_tokens", return_value=None):
                result = get_google_credentials_for_tenant("tenant-1")

    service_refresh.assert_called_once_with()
    assert result["access_token"] == "fresh-token"
