"""Regression checks for Google Ads support through the unchanged GPT Action."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from app.core import google_ads_gateway as ads
from app.main import openapi_gpt_schema


def test_original_schema_keeps_existing_actions():
    paths = openapi_gpt_schema()["paths"]
    for name in ("/tools/intent", "/meta/query", "/meta/request", "/analysis/run", "/comment_automations/manage"):
        assert name in paths
    assert "/google_ads" not in paths


def test_natural_egyptian_request():
    body = SimpleNamespace(request="حلل إعلانات جوجل النهارده 123-456-7890", meta_account_id=None)
    command = ads.parse_google_ads_request(body)
    assert command["customer_id"] == "123-456-7890"
    assert command["date_range"] == "TODAY"
    assert command["action"] == "report"


def test_json_command_is_parsed():
    body = SimpleNamespace(request='google_ads {"action":"report","customer_id":"1234567890","report":"keywords"}', meta_account_id=None)
    assert ads.parse_google_ads_request(body)["report"] == "keywords"


def test_invalid_credentials_rejected():
    assert not ads._detect("اعمل تحليل ميتا")
    with pytest.raises(HTTPException):
        ads._customer_id("foo")
    with pytest.raises(HTTPException):
        ads._check_mutations([{"campaignOperation": {"remove": "customers/0000000000/campaigns/1"}}], "1234567890")


def test_mutation_is_two_stage_and_single_use(monkeypatch):
    effects = []
    monkeypatch.setattr(ads, "_api", lambda *a, **k: effects.append((a,k)) or {})
    monkeypatch.setattr(ads, "create_auth_code", lambda *a, **k: "code_dummy")
    uses = []
    monkeypatch.setattr(ads, "consume_auth_code", lambda code: uses.append(code) or (
        {"tenant_id": "tenant-a", "meta_user_id": "google_ads_mutation_approval"} if len(uses) == 1 else None
    ))
    monkeypatch.setattr(ads, "_signer", lambda salt: ads.URLSafeTimedSerializer("test-secret", salt=salt))
    ident = {"tenant_id": "tenant-a"}
    operations = [{"campaignOperation": {"update": {
        "resourceName": "customers/1234567890/campaigns/1",
        "status": "PAUSED",
    }}}]
    preview = ads.execute_google_ads_command({
        "action": "prepare_mutation", "customer_id": "1234567890", "operations": operations,
    }, ident)
    assert preview["status"] == "AWAITING_USER_CONFIRMATION"
    assert len(effects) == 1
    assert effects[0][0][3]["validateOnly"] is True
    with pytest.raises(HTTPException):
        ads.execute_google_ads_command({
            "action": "commit_mutation", "approval_token": preview["approval_token"],
            "confirmation_phrase": "WRONG",
        }, ident)
    assert len(effects) == 1
    committed = ads.execute_google_ads_command({
        "action": "commit_mutation", "approval_token": preview["approval_token"],
        "confirmation_phrase": "CONFIRM_GOOGLE_ADS_CHANGE",
    }, ident)
    assert committed["status"] == "APPLIED"
    assert len(effects) == 2 and uses == ["code_dummy"]
    with pytest.raises(HTTPException):
        ads.execute_google_ads_command({
            "action": "commit_mutation", "approval_token": preview["approval_token"],
            "confirmation_phrase": "CONFIRM_GOOGLE_ADS_CHANGE",
        }, ident)
