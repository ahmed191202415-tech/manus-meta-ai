from copy import deepcopy

import pytest
from fastapi import HTTPException

from app.core import google_ads_gateway as ads
from app.core.google_ads_query import prepare_query, finalize_query


def query(**extras):
    return {"action": "query", "customer_id": "3333735582",
            "query": "SELECT campaign.id FROM campaign", **extras}


@pytest.mark.parametrize("extras", [
    {"campaign_id": "24445941074"}, {"start_date": "2026-11-16"}, {"report": "search_terms"},
    {"search_stream": "false"}, {"limit": "all"}, {"limit": True}, {"limit": 0},
])
def test_query_never_ignores_scope_or_malformed_controls(extras):
    with pytest.raises(HTTPException) as exc:
        prepare_query(query(**extras))
    assert exc.value.status_code == 422


def test_query_is_bounded_without_changing_literal_contents():
    text = 'SELECT campaign.id FROM campaign WHERE campaign.name = "SMS; -- Test LIMIT 9" PARAMETERS omit_unselected_resource_names=true'
    plan = prepare_query(query(query=text, limit=50, search_stream=True))
    assert '"SMS; -- Test LIMIT 9" LIMIT 51 PARAMETERS' in plan["query"]
    assert plan["read_limit"] == 51
    assert plan["requested_query"] == text


def test_existing_limit_is_never_widened_and_is_disclosed():
    plan = prepare_query(query(query="SELECT campaign.id FROM campaign LIMIT 2"))
    assert plan["query"].endswith("LIMIT 2")
    result = finalize_query(plan, {"rows": [{"campaign": {"id": "1"}}, {"campaign": {"id": "2"}}], "truncated": False})
    assert result["query_limited"] is True and result["partial"] is True


def test_user_big_limit_and_query_are_bounded_with_extra_row():
    plan = prepare_query(query(query="SELECT campaign.id FROM campaign LIMIT 999999", limit=1000))
    assert plan["query"].endswith("LIMIT 301")
    assert plan["display_limit"] == 300


@pytest.mark.parametrize("text", [
    "SELECT campaign.id FROM campaign; DELETE campaign",
    "SELECT campaign.id FROM campaign -- comment",
    "SELECT campaign.id FROM campaign LIMIT abc",
    "SELECT campaign.id FROM campaign LIMIT 1 LIMIT 2",
    "SELECT campaign.id FROM campaign WHERE campaign.name = 'unclosed",
])
def test_ambiguous_gaql_rejected_before_api(text):
    with pytest.raises(HTTPException):
        prepare_query(query(query=text))


OPS = [{"campaignOperation": {"update": {
    "resourceName": "customers/3333735582/campaigns/24445941074", "status": "PAUSED"},
    "updateMask": "status"}}]


@pytest.mark.parametrize("body", [{}, {"mutateOperationResponses": []},
    {"mutateOperationResponses": [{"campaignResult": {"resourceName": "customers/9999999999/campaigns/24445941074"}}]},
    {"mutateOperationResponses": [{"campaignResult": {"resourceName": "customers/3333735582/campaigns/999"}}]},
    {"mutateOperationResponses": [{}]}])
def test_empty_or_mismatched_mutation_never_claims_applied(body):
    with pytest.raises(HTTPException) as exc:
        ads._mutation_response(body, OPS, "3333735582")
    assert exc.value.detail["status"] == "MUTATION_OUTCOME_UNKNOWN"
    assert exc.value.detail["retryable"] is False


def test_validate_only_accepts_empty_success_without_applying_changes():
    assert ads._mutation_response({}, OPS, "3333735582", validate_only=True) == []


def test_partial_failure_200_is_not_success():
    with pytest.raises(HTTPException) as exc:
        ads._mutation_response({"partialFailureError": {
            "code": 3, "details": [{"errors": [{"errorCode": {"fieldMaskError": "FIELD_MASK_MISSING"}}]}]
        }}, OPS, "3333735582")
    assert exc.value.detail["google_ads_error_code"] == "FIELD_MASK_MISSING"


@pytest.mark.parametrize("mask", ["", "*", "status, bad path", "resourceName;status"])
def test_mutation_requires_explicit_field_mask(mask):
    ops = deepcopy(OPS)
    ops[0]["campaignOperation"]["updateMask"] = mask
    with pytest.raises(HTTPException) as exc:
        ads._check_mutations(ops, "3333735582")
    assert exc.value.status_code == 422


def test_modified_preview_cannot_consume_or_apply_approval(monkeypatch):
    monkeypatch.setattr(ads, "_signer", lambda salt: ads.URLSafeTimedSerializer("test", salt=salt))
    token = ads._signer("google-ads-mut-v1").dumps({
        "tenant_id": "tenant", "customer_id": "3333735582", "operations": OPS, "approval_code": "test"})
    monkeypatch.setattr(ads, "consume_auth_code", lambda code: pytest.fail("Cannot consume changed preview"))
    with pytest.raises(HTTPException) as exc:
        ads.execute_google_ads_command({
            "action": "commit_mutation", "approval_token": token,
            "confirmation_phrase": "CONFIRM_GOOGLE_ADS_CHANGE", "operations": [],
        }, {"tenant_id": "tenant"})
    assert exc.value.status_code == 403
