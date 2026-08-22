from app.core.dashboard_store import DashboardStore


def _store(get_dashboard=lambda dashboard_id: None, create_dashboard=lambda **kwargs: kwargs, update_dashboard=lambda *args: None):
    return DashboardStore({}, {}, create_dashboard, get_dashboard, update_dashboard)


def test_code_contract_is_normalized_into_runtime_definition():
    definition = DashboardStore.definition_from_code({
        "dashboard_id": "sales",
        "data_contract": {
            "queries": {"funnel": {"nodes": []}},
            "formulas": {"roas": {"expression": "revenue / spend"}},
        },
    })

    assert definition["runtime_queries"]["funnel"] == {"nodes": []}
    assert definition["metrics"]["roas"]["expression"] == "revenue / spend"


def test_save_definition_does_not_mutate_caller_payload():
    payload = {"title": "Sales"}
    store = _store()

    saved = store.save_definition(payload, "sales")

    assert payload == {"title": "Sales"}
    assert saved["dashboard_id"] == "sales"


def test_deleted_persistent_dashboard_is_not_returned():
    store = _store(get_dashboard=lambda dashboard_id: {"dashboard_id": dashboard_id, "status": "deleted"})

    assert store.stored_row("deleted") is None


def test_runtime_context_manifest_takes_priority_without_changing_cache():
    store = _store()
    context = {"manifest": {"title": "Preview"}}

    definition = store.runtime_definition("preview", {"dashboard_id": "default"}, context)

    assert definition == {"title": "Preview", "dashboard_id": "preview"}
    assert store.definitions == {}

