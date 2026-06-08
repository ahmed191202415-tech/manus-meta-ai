from fastapi import HTTPException

from app.core import ga4_client


def test_resolve_ga4_property_uses_single_discovered_property(monkeypatch):
    monkeypatch.setattr(ga4_client, "get_google_connection_or_401", lambda tenant_id: {"selected_ga4_property_id": ""})
    monkeypatch.setattr(
        ga4_client,
        "list_ga4_properties",
        lambda tenant_id: [{"property_id": "529884683", "property_name": "BeOn"}],
    )

    assert ga4_client.resolve_ga4_property_id("tenant@example.com") == "529884683"


def test_resolve_ga4_property_returns_selection_options_when_many_exist(monkeypatch):
    monkeypatch.setattr(ga4_client, "get_google_connection_or_401", lambda tenant_id: {"selected_ga4_property_id": ""})
    monkeypatch.setattr(
        ga4_client,
        "list_ga4_properties",
        lambda tenant_id: [
            {"property_id": "1", "property_name": "One"},
            {"property_id": "2", "property_name": "Two"},
        ],
    )

    try:
        ga4_client.resolve_ga4_property_id("tenant@example.com")
    except HTTPException as exc:
        assert exc.status_code == 400
        assert exc.detail["reason"] == "property_selection_required"
        assert len(exc.detail["available_properties"]) == 2
    else:
        raise AssertionError("Expected property selection error.")
