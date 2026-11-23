"""Bulk EXACT negatives are a preview, never an automatic write."""
from types import SimpleNamespace
from fastapi import HTTPException
import pytest
from app.core import google_ads_gateway as ads
from app.core.google_ads_intent import parse_google_ads_request

CID = "3333735582"
GID = "208243021384"

def cmd(words):
    return {"action": "prepare_negative_keywords", "customer_id": CID,
            "campaign_name": "Sales-Search-1", "ad_group_id": GID,
            "match_type": "EXACT", "keywords": words}

def setup(monkeypatch, existing=()):
    calls = []
    def read(query, tenant, customer, manager_id=None, limit=100):
        calls.append(query)
        if "FROM ad_group " in query:
            return {"rows": [{"adGroup": {"id": GID},
                              "campaign": {"id": "24412747386", "name": "Sales-Search-1"}}]}
        return {"rows": [{"adGroupCriterion": {"keyword": {"text": term, "matchType": "EXACT"}}}
                         for term in existing], "truncated": False}
    def api(tenant, method, path, body=None, manager_id=None):
        assert body["validateOnly"] is True
        assert body["partialFailure"] is False
        return {"mutateOperationResponses": []}
    monkeypatch.setattr(ads, "_read", read)
    monkeypatch.setattr(ads, "_api", api)
    monkeypatch.setattr(ads, "create_auth_code", lambda *args, **kw: "approval-code")
    return calls

def test_24_negative_keywords_validate_only_no_commit(monkeypatch):
    setup(monkeypatch)
    words = ["exact sms negative " + str(i) for i in range(24)]
    result = ads._prepare_negative_keywords("tenant", cmd(words))
    assert result["status"] == "AWAITING_USER_CONFIRMATION"
    assert len(result["operations"]) == 24
    assert result["no_changes_applied"] is True
    for operation in result["operations"]:
        created = operation["adGroupCriterionOperation"]["create"]
        assert created["adGroup"] == f"customers/{CID}/adGroups/{GID}"
        assert created["negative"] is True
        assert created["keyword"]["matchType"] == "EXACT"

def test_dedupes_bracketed_and_existing_words(monkeypatch):
    setup(monkeypatch, existing=["receive sms"])
    result = ads._prepare_negative_keywords("tenant", cmd(["[receive sms]", "SEND FREE SMS", "[send free sms]"]))
    assert result["already_present"] == ["receive sms"]
    assert result["new_keywords"] == ["SEND FREE SMS"]
    assert len(result["operations"]) == 1

def test_campaign_mismatch_is_rejected_before_validation(monkeypatch):
    setup(monkeypatch)
    command = cmd(["abc"])
    command["campaign_id"] = "99999"
    with pytest.raises(HTTPException) as err:
        ads._prepare_negative_keywords("tenant", command)
    assert err.value.status_code == 422

def test_natural_language_without_explicit_json_not_mutation():
    result = parse_google_ads_request(SimpleNamespace(
        request="google_ads أضف الكلمات المستبعدة على SMS في حملة Sales-Search-1",
        meta_account_id=CID, campaign_name=None))
    assert result["action"] != "commit_mutation"

def test_json_write_routes_to_bulk_preview():
    import json
    result = parse_google_ads_request(SimpleNamespace(
        request="google_ads " + json.dumps(cmd(["[send free sms]"]), ensure_ascii=False),
        meta_account_id=CID, campaign_name=None))
    assert result["action"] == "prepare_negative_keywords"
    assert result["keywords"] == ["[send free sms]"]

def test_too_many_words_rejected():
    with pytest.raises(HTTPException) as err:
        ads._prepare_negative_keywords("tenant", cmd(["word" + str(i) for i in range(51)]))
    assert err.value.status_code == 422
