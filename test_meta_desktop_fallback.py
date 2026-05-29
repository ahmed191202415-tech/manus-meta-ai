from app.api.auth_meta import _is_desktop_app_error, _meta_login_url


def test_detects_meta_desktop_app_error():
    assert _is_desktop_app_error({
        "error": {
            "message": "The request is invalid because the app is configured as a desktop app",
            "type": "OAuthException",
        }
    })


def test_meta_token_fallback_url_uses_response_type_token():
    url = _meta_login_url(
        {"meta_app_id": "123", "meta_oauth_scopes": "ads_read"},
        "state-token",
        response_type="token",
    )
    assert "response_type=token" in url
    assert "scope=ads_read" in url
    assert "client_id=123" in url
