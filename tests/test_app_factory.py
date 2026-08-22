from app.main import app, create_app


def test_app_factory_builds_independent_apps_with_same_routes():
    first = create_app()
    second = create_app()

    assert first is not second
    assert set(first.openapi()["paths"]) == set(second.openapi()["paths"])
    assert "/api/dashboard-runtime/v2/workflow" in first.openapi()["paths"]


def test_exported_app_keeps_gpt_schema_route_out_of_regular_openapi():
    assert "/openapi-gpt.json" not in app.openapi()["paths"]
    assert any(getattr(route, "path", None) == "/openapi-gpt.json" for route in app.routes)
