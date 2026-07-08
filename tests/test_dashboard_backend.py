import asyncio

from app.api import dynamic_dashboards


def _dashboard_row(render_mode="manifest"):
    return {
        "dashboard_id": "dash_1",
        "tenant_id": "tenant_1",
        "title": "Operations Dashboard",
        "description": "Any backend data",
        "status": "active",
        "config": {
            "render_mode": render_mode,
            "html": "<main id='app'></main>",
            "css": "#app{padding:20px}",
            "javascript": "document.getElementById('app').textContent=ALLINGPT.dataset('orders').length",
            "data_contract": {"metrics": {"revenue": {"source": "dataset", "field": "value"}}},
            "data_sources": [{"source": "dataset", "name": "orders", "dataset_id": "data_1"}],
        },
        "snapshot": {"manual_note": "ready"},
        "refresh_policy": {"mode": "on_open"},
        "last_refreshed_at": None,
    }


def test_dashboard_data_includes_linked_arbitrary_dataset(monkeypatch):
    monkeypatch.setattr(dynamic_dashboards, "get_dynamic_dashboard", lambda dashboard_id: _dashboard_row())
    monkeypatch.setattr(
        dynamic_dashboards,
        "list_dashboard_datasets",
        lambda tenant_id, dashboard_id=None, limit=100: [
            {"dataset_id": "data_1", "tenant_id": tenant_id, "dashboard_id": dashboard_id, "name": "orders", "status": "active"}
        ],
    )
    monkeypatch.setattr(
        dynamic_dashboards,
        "list_dashboard_dataset_records",
        lambda tenant_id, dataset_id, limit=500: [
            {
                "record_id": "rec_1",
                "dataset_id": dataset_id,
                "external_key": "A-1",
                "data": {"order_id": "A-1", "customer": "Ahmed", "value": 250},
                "created_at": "2026-06-21T00:00:00Z",
                "updated_at": "2026-06-21T00:00:00Z",
            }
        ],
    )

    result = asyncio.run(dynamic_dashboards.dashboard_data("dash_1"))

    assert result["snapshot"]["manual_note"] == "ready"
    assert result["snapshot"]["orders"][0]["customer"] == "Ahmed"
    assert result["snapshot"]["data_1"][0]["value"] == 250
    assert result["datasets"][0]["row_count"] == 1


def test_dashboard_data_survives_missing_dataset_tables(monkeypatch):
    monkeypatch.setattr(dynamic_dashboards, "get_dynamic_dashboard", lambda dashboard_id: _dashboard_row())

    def missing_table(*args, **kwargs):
        raise RuntimeError("relation dashboard_datasets does not exist")

    monkeypatch.setattr(dynamic_dashboards, "list_dashboard_datasets", missing_table)

    result = asyncio.run(dynamic_dashboards.dashboard_data("dash_1"))

    assert result["snapshot"]["manual_note"] == "ready"
    assert result["datasets"] == []
    assert result["warnings"][0]["source"] == "dashboard_datasets"


def test_code_dashboard_is_persistent_and_uses_backend_datasets(monkeypatch):
    row = _dashboard_row(render_mode="code")
    monkeypatch.setattr(dynamic_dashboards, "list_dashboard_datasets", lambda *args, **kwargs: [])
    monkeypatch.setattr(dynamic_dashboards, "get_dashboard_dataset", lambda *args, **kwargs: None)

    html = dynamic_dashboards._code_dashboard_html(row)

    assert "window.ALLINGPT" in html
    assert "dataset(nameOrId)" in html
    assert "/api/dashboard-runtime/query" in html
    assert "Any backend data" in html


def test_dataset_query_supports_nested_filters_search_and_sort(monkeypatch):
    class Request:
        session = {"tenant_id": "tenant_1"}
        headers = {}

    monkeypatch.setattr(
        dynamic_dashboards,
        "get_dashboard_dataset",
        lambda tenant_id, dataset_id: {"dataset_id": dataset_id, "tenant_id": tenant_id, "name": "orders", "status": "active"},
    )
    monkeypatch.setattr(
        dynamic_dashboards,
        "list_dashboard_dataset_records",
        lambda *args, **kwargs: [
            {"record_id": "1", "external_key": "A", "data": {"customer": {"city": "Cairo"}, "value": 100}},
            {"record_id": "2", "external_key": "B", "data": {"customer": {"city": "Cairo"}, "value": 300}},
            {"record_id": "3", "external_key": "C", "data": {"customer": {"city": "Giza"}, "value": 500}},
        ],
    )
    body = dynamic_dashboards.DashboardDatasetQueryRequest(
        dataset_id="data_1",
        filters={"customer.city": "Cairo", "value": {"gte": 150}},
        search="Cairo",
        sort_by="value",
        sort_order="desc",
    )

    result = asyncio.run(dynamic_dashboards.query_dataset(body, Request()))

    assert result["matched_count"] == 1
    assert result["records"][0]["value"] == 300
