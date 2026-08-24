from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_dashboard_console_requires_tenant_session():
    response = client.get("/dashboard-runtime/console")

    assert response.status_code == 401


def test_dashboard_console_routes_are_registered_outside_gpt_schema():
    assert client.post("/dashboard-runtime/console/preview").status_code == 422
    assert client.post("/dashboard-runtime/console/publish").status_code == 422
    assert "/dashboard-runtime/console" not in app.openapi()["paths"]
