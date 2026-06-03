from app.config import META_OAUTH_SCOPES


def test_default_meta_oauth_scopes_include_lead_ads_form_access():
    scopes = {item.strip() for item in META_OAUTH_SCOPES.split(",") if item.strip()}

    assert "leads_retrieval" in scopes
    assert "pages_manage_ads" in scopes
