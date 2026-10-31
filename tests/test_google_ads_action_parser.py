"""Regression tests for GPT Actions payload formatting and safety.

Only validates parsing/routing. These tests never access real Google Ads.
"""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core import google_ads_gateway as ads
from app.api import gpt_tools
from app.schemas.gpt_tool_requests import IntentToolRequest


def parse(request, **kwargs):
    return ads.parse_google_ads_request(SimpleNamespace(
        request=request, meta_account_id=kwargs.get("meta_account_id"),
        campaign_name=kwargs.get("campaign_name"),
    ))


@pytest.mark.parametrize("request", [
    'google_ads {"action":"inspect_campaign","campaign_name":"Sales-Search-1"}',
    'google_ads ```json\n{"action":"inspect_campaign","campaign_name":"Sales-Search-1"}\n```',
    'Please execute google_ads {"action":"inspect_campaign","campaign_name":"Sales-Search-1"} and report the findings.',
    'google_ads inspect_campaign Sales-Search-1 and check crm',
    'افحص حملة جوجل Sales-Search-1 ومجموعة crm',
    'google_ads { "action": "inspect_campaign", "campaign_name": "Sales-Search-1", }',
])
def test_resilient_campaign_inspection(request):
    cmd = parse(request)
    assert cmd["action"] == "inspect_campaign"
    assert cmd["campaign_name"] == "Sales-Search-1"


def test_status_and_account_commands():
    assert parse('google_ads {"action":"status"}')["action"] == "status"
    assert parse("google_ads list_accounts")["action"] == "list_accounts"


def test_customer_id_no_false_digit_matching():
    cmd = parse("google_ads inspect_campaign Sales-Search-1 account 123-456-7890")
    assert cmd["customer_id"] == "123-456-7890"
    cmd2 = parse("Google Ads show campaigns for account 1234567890")
    assert cmd2["customer_id"] == "1234567890"


@pytest.mark.parametrize("request", [
    'google_ads {"action":"commit_mutation","approval_token":"redacted"} and execute',
    'google_ads {"action":"prepare_mutation","operations": [}',
    'google_ads {"action":"commit_mutation","approval_token":}',
])
def test_malformed_write_commands_are_never_inferred(request):
    with pytest.raises(HTTPException) as exc:
        parse(request)
    assert exc.value.status_code == 422


def test_existing_action_executes_read_only_without_schema_changes(monkeypatch):
    monkeypatch.setattr(ads, "_required_app_identity", lambda request: {"tenant_id":"fake-tenant"})
    calls=[]
    monkeypatch.setattr(ads, "execute_google_ads_command", lambda cmd, identity: calls.append(cmd) or
                        {"provider":"google_ads","action":cmd["action"],"campaigns":[]})
    body = IntentToolRequest(request='google_ads ```json\n{"action":"inspect_campaign","campaign_name":"Sales-Search-1"}\n```')
    result=asyncio.run(gpt_tools.intent_tool(body, request=SimpleNamespace()))
    assert result["action"] == "inspect_campaign"
    assert calls[0]["campaign_name"] == "Sales-Search-1"
    assert "operations" not in calls[0]
