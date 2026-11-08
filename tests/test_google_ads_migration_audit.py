"""One-shot Google Ads CRM migration audit remains read-only and partial-safe."""
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app, openapi_gpt_schema
from app.core import google_ads_gateway as gateway
from app.core import google_ads_migration_audit as audit


def _fake_read(query, tenant, customer_id, manager_id=None, limit=100):
    assert tenant == "tenant-test"
    assert customer_id == "3333735582"
    if "FROM campaign WHERE" in query:
        return {"rows":[{"campaign":{"id":"24387253876","name":"Sales-Search-1"}}], "truncated":False}
    if "FROM ad_group WHERE" in query:
        return {"rows":[{"campaign":{"id":"24387253876"},"adGroup":{"id":"204483944314","name":"crm"}}], "truncated":False}
    if "FROM ad_group_criterion" in query and "type = 'KEYWORD'" in query:
        return {"rows":[{"adGroupCriterion":{"keyword":{"text":"crm software","matchType":"PHRASE"},"status":"ENABLED"}}], "truncated":False}
    if "FROM ad_group_ad" in query:
        return {"rows":[{"adGroupAd":{"ad":{"id":"12","type":"RESPONSIVE_SEARCH_AD","finalUrls":["https://example.com"]}}}], "truncated":False}
    return {"rows":[], "truncated":False}


def test_audit_returns_nine_complete_sections_without_any_write(monkeypatch):
    monkeypatch.setattr(gateway,"_read",_fake_read)
    result=audit.audit_crm_migration("tenant-test","333-373-5582","24387253876","204483944314")
    assert result["mode"] == "READ_ONLY"
    assert result["identity_verified"] is True
    assert result["audit_complete"] is True
    assert result["safe_to_clone_automatically"] is False
    assert len(result["sections"]) == 9
    assert result["sections"]["keywords"]["rows"][0]["adGroupCriterion"]["keyword"]["text"] == "crm software"


def test_failed_section_keeps_other_data_and_flags_incomplete(monkeypatch):
    def broken_read(*args, **kwargs):
        if "FROM ad_group_ad" in args[0]:
            raise HTTPException(403,{
                "origin":"google_ads_api", "api_status":"PERMISSION_DENIED",
                "google_ads_error_code":"CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION",
                "next_step":"Check Explorer approval"
            })
        return _fake_read(*args,**kwargs)
    monkeypatch.setattr(gateway,"_read",broken_read)
    result=audit.audit_crm_migration("tenant-test","3333735582","24387253876","204483944314")
    assert result["audit_complete"] is False
    assert result["failed_sections"] == ["ads"]
    assert result["sections"]["ads"]["error"]["google_ads_error_code"] == "CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION"
    assert result["sections"]["keywords"]["ok"] is True


def test_wrong_parent_ids_never_pass_identity_check(monkeypatch):
    def wrong(query, *args, **kwargs):
        result=_fake_read(query,*args,**kwargs)
        if "FROM ad_group WHERE" in query:
            result["rows"][0]["campaign"]["id"]="999"
        return result
    monkeypatch.setattr(gateway,"_read",wrong)
    result=audit.audit_crm_migration("tenant-test","3333735582","24387253876","204483944314")
    assert result["identity_verified"] is False
    assert result["audit_complete"] is False


def test_existing_action_routes_audit_json_only_to_google_handler(monkeypatch):
    monkeypatch.setattr(gateway,"_required_app_identity",lambda _:{"tenant_id":"tenant-test"})
    monkeypatch.setattr(gateway,"_read",_fake_read)
    response=TestClient(app).post("/tools/intent",json={
        "request":'google_ads {"action":"audit_crm_migration","customer_id":"3333735582","campaign_id":"24387253876","ad_group_id":"204483944314"}'
    })
    assert response.status_code==200, response.text
    data=response.json()
    assert data["mode"]=="READ_ONLY"
    assert data["action"]=="audit_crm_migration"
    assert data["sections"]["ads"]["ok"] is True
    assert data["action_diagnostics"]["route"]=="/tools/intent"
    assert len(openapi_gpt_schema()["paths"])==28


def test_missing_or_bad_ids_rejected_before_api_reads(monkeypatch):
    monkeypatch.setattr(gateway,"_read",lambda *args,**kwargs: (_ for _ in ()).throw(AssertionError("No API request expected")))
    for cid, campaign, group in [
        ("3333735582","bad","204483944314"),
        ("3333735582","24387253876","1;DROP"),
        ("1234","24387253876","204483944314"),
    ]:
        try:
            audit.audit_crm_migration("tenant-test",cid,campaign,group)
        except HTTPException as exc:
            assert exc.status_code==422
        else:
            raise AssertionError("Unsafe ID accepted")
