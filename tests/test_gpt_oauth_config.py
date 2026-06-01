from fastapi.testclient import TestClient

from app.main import app


def test_gpt_oauth_config_exposes_client_id_but_not_secret():
    response = TestClient(app).get("/oauth/config")

    assert response.status_code == 200
    payload = response.json()
    assert payload["client_id"]
    assert payload["authorization_url"].endswith("/oauth/authorize")
    assert payload["token_url"].endswith("/oauth/token")
    assert "GPT_OAUTH_CLIENT_SECRET" in payload["client_secret"]
