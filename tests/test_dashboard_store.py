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


def test_persisted_dynamic_manifest_is_normalized_without_definition_wrapper():
    row = {
        "dashboard_id": "dash_live",
        "tenant_id": "tenant_1",
        "title": "Live Funnel",
        "status": "active",
        "config": {
            "render_mode": "manifest",
            "filters": [{"key": "account_id", "type": "select"}],
            "widgets": [{"id": "funnel", "type": "funnel", "data_query": "journey_funnel"}],
            "data_sources": [{"source": "meta", "name": "meta"}],
            "data_contract": {
                "runtime_queries": {
                    "accounts": {"connector": "meta", "resource": "accounts"},
                },
                "stages": [{"id": "landing", "label": "Landing"}],
            },
        },
    }
    store = _store(get_dashboard=lambda dashboard_id: row)

    definition = store.runtime_definition("dash_live", {"dashboard_id": "customer_journey"})

    assert definition["dashboard_id"] == "dash_live"
    assert definition["tenant_id"] == "tenant_1"
    assert definition["filters"][0]["key"] == "account_id"
    assert definition["runtime_queries"]["accounts"]["resource"] == "accounts"
    assert definition["data_sources"]["meta"]["source"] == "meta"


def test_unknown_dashboard_never_inherits_another_dashboard_definition():
    default = {"dashboard_id": "customer_journey", "runtime_queries": {"accounts": {"legacy": True}}}

    definition = _store().runtime_definition("missing_dashboard", default)

    assert definition == {
        "dashboard_id": "missing_dashboard",
        "runtime_queries": {},
        "_runtime_resolution": "not_found",
    }
