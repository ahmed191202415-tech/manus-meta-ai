from unittest.mock import patch

from app.core.oauth_store import purge_tenant_integrations


def test_purge_tenant_integrations_removes_all_saved_connections():
    deleted = []

    def fake_delete(table, params):
        deleted.append((table, params))
        return True

    with patch("app.core.oauth_store._delete", side_effect=fake_delete):
        with patch("app.core.oauth_store.delete_app_tokens", return_value=True) as delete_tokens:
            assert purge_tenant_integrations("client@example.com") is True

    delete_tokens.assert_called_once_with(tenant_id="client@example.com")
    assert ("oauth_codes", {"tenant_id": "eq.client@example.com"}) in deleted
    assert ("meta_connections", {"tenant_id": "eq.client@example.com"}) in deleted
    assert ("tenant_meta_apps", {"tenant_id": "eq.client@example.com"}) in deleted
    assert ("google_connections", {"tenant_id": "eq.client@example.com"}) in deleted
    assert ("clarity_connections", {"tenant_id": "eq.client@example.com"}) in deleted
