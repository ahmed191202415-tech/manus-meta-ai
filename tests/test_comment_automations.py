import hashlib
import hmac

import pytest
from pydantic import ValidationError

from app.api import webhooks
from app.schemas.comment_automation_requests import CommentAutomationManageRequest


def test_extract_comment_events_keeps_new_external_page_comments_only():
    payload = {
        "entry": [
            {
                "id": "page_1",
                "changes": [
                    {
                        "field": "feed",
                        "value": {
                            "item": "comment",
                            "verb": "add",
                            "comment_id": "comment_1",
                            "post_id": "post_1",
                            "from": {"id": "customer_1"},
                            "message": "Interested",
                        },
                    },
                    {
                        "field": "feed",
                        "value": {
                            "item": "comment",
                            "verb": "edited",
                            "comment_id": "comment_2",
                            "post_id": "post_1",
                            "from": {"id": "customer_1"},
                        },
                    },
                    {
                        "field": "feed",
                        "value": {
                            "item": "comment",
                            "verb": "add",
                            "comment_id": "comment_3",
                            "post_id": "post_1",
                            "from": {"id": "page_1"},
                        },
                    },
                ],
            }
        ]
    }

    assert webhooks.extract_comment_events(payload) == [
        {
            "page_id": "page_1",
            "post_id": "post_1",
            "comment_id": "comment_1",
            "commenter_id": "customer_1",
            "message": "Interested",
        }
    ]


def test_rule_matches_comment_supports_all_comments_and_casefold_keyword():
    event = {"message": "I WANT Price Details"}

    assert webhooks.rule_matches_comment({"match_mode": "all_comments"}, event) is True
    assert webhooks.rule_matches_comment({"match_mode": "contains_keyword", "keyword": "price"}, event) is True
    assert webhooks.rule_matches_comment({"match_mode": "contains_keyword", "keyword": "demo"}, event) is False


def test_process_rule_sends_public_private_and_hide_once(monkeypatch):
    calls = []
    completed = []
    rule = {
        "rule_id": "rule_1",
        "tenant_id": "tenant_1",
        "page_id": "page_1",
        "page_access_token": "page_token",
        "post_id": "post_1",
        "public_reply_message": "Public answer",
        "private_reply_message": "Private answer",
        "hide_comment": True,
    }
    event = {
        "page_id": "page_1",
        "post_id": "post_1",
        "comment_id": "comment_1",
        "commenter_id": "customer_1",
        "message": "hello",
    }

    monkeypatch.setattr(webhooks, "begin_comment_automation_log", lambda rule, event: {"log_id": "log_1"})
    monkeypatch.setattr(webhooks, "_meta_app_secret_for_rule", lambda rule: "secret")
    monkeypatch.setattr(
        webhooks,
        "send_facebook_private_reply",
        lambda event, message, token, app_secret=None: calls.append(
            ("PRIVATE_REPLY", event["comment_id"], token, {"message": message}, app_secret)
        ) or {"mode": "comment_private_replies"},
    )
    monkeypatch.setattr(webhooks, "finish_comment_automation_log", lambda log_id, payload: completed.append((log_id, payload)))
    monkeypatch.setattr(
        webhooks,
        "meta_call",
        lambda method, path, access_token, params=None, data=None, app_secret=None: calls.append(
            (method, path, access_token, data, app_secret)
        ) or {"success": True},
    )

    webhooks._process_rule(rule, event)

    assert calls == [
        ("POST", "comment_1/comments", "page_token", {"message": "Public answer"}, "secret"),
        (
            "PRIVATE_REPLY",
            "comment_1",
            "page_token",
            {"message": "Private answer"},
            "secret",
        ),
        ("POST", "comment_1", "page_token", {"is_hidden": True}, "secret"),
    ]
    assert completed == [
        (
            "log_1",
            {
                "public_reply_status": "sent",
                "private_reply_status": "sent",
                "hide_status": "hidden",
                "error_message": "",
            },
        )
    ]


def test_process_rule_skips_duplicate_webhook_delivery(monkeypatch):
    monkeypatch.setattr(webhooks, "begin_comment_automation_log", lambda rule, event: None)
    monkeypatch.setattr(webhooks, "meta_call", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not call Meta")))

    webhooks._process_rule({"rule_id": "rule_1"}, {"comment_id": "comment_1"})


def test_signature_validation_uses_tenant_meta_app_secret(monkeypatch):
    payload = b'{"object":"page"}'
    digest = hmac.new(b"tenant-secret", payload, hashlib.sha256).hexdigest()
    monkeypatch.setattr(webhooks, "META_APP_SECRET", "")
    monkeypatch.setattr(
        webhooks,
        "list_enabled_comment_automation_rules_for_page",
        lambda page_id: [{"tenant_id": "tenant_1"}],
    )
    monkeypatch.setattr(webhooks, "get_tenant_meta_app", lambda tenant_id: {"meta_app_secret": "tenant-secret"})

    assert webhooks.is_valid_meta_webhook_signature(
        payload,
        f"sha256={digest}",
        [{"page_id": "page_1", "post_id": "post_1"}],
    ) is True


def test_list_comments_requires_page_and_post_ids():
    with pytest.raises(ValidationError):
        CommentAutomationManageRequest(action="list_comments", page_id="page_1")

    request = CommentAutomationManageRequest(action="list_comments", page_id="page_1", post_id="post_1")
    assert request.action == "list_comments"


def test_process_comment_events_logs_missing_rule(monkeypatch):
    logged = []
    payload = {
        "entry": [
            {
                "id": "page_1",
                "changes": [
                    {
                        "field": "feed",
                        "value": {
                            "item": "comment",
                            "verb": "add",
                            "comment_id": "comment_1",
                            "post_id": "post_1",
                            "from": {"id": "customer_1"},
                            "message": "hello",
                        },
                    }
                ],
            }
        ]
    }
    monkeypatch.setattr(webhooks, "list_enabled_comment_automation_rules_for_post", lambda page_id, post_id: [])
    monkeypatch.setattr(webhooks, "list_enabled_comment_automation_rules_for_alias", lambda page_id, post_id: [])
    monkeypatch.setattr(webhooks, "save_comment_webhook_event", lambda event, status, **kwargs: logged.append((event, status, kwargs)))

    webhooks.process_comment_events(payload)

    assert logged[0][1] == "unmapped_ad_post"


def test_process_comment_events_logs_keyword_mismatch(monkeypatch):
    logged = []
    monkeypatch.setattr(webhooks, "extract_comment_events", lambda payload: [{"page_id": "page_1", "post_id": "post_1", "comment_id": "comment_1", "message": "hello"}])
    monkeypatch.setattr(
        webhooks,
        "list_enabled_comment_automation_rules_for_post",
        lambda page_id, post_id: [{"tenant_id": "tenant_1", "match_mode": "contains_keyword", "keyword": "price"}],
    )
    monkeypatch.setattr(webhooks, "save_comment_webhook_event", lambda event, status, **kwargs: logged.append((event, status, kwargs)))

    webhooks.process_comment_events({})

    assert logged[0][1] == "keyword_not_matched"


def test_private_reply_falls_back_for_composite_comment_id(monkeypatch):
    calls = []

    def meta_call(method, path, token, params=None, data=None, app_secret=None):
        calls.append((path, data))
        if path != "page_1/messages":
            raise webhooks.HTTPException(
                status_code=400,
                detail={"code": 100, "error_subcode": 33, "message": "Unsupported post request"},
            )
        return {"message_id": "message_1"}

    monkeypatch.setattr(webhooks, "meta_call", meta_call)

    result = webhooks.send_facebook_private_reply(
        {"page_id": "page_1", "comment_id": "122210969480562448_1704741537204014"},
        "Private answer",
        "page_token",
    )

    assert result["mode"] == "page_messages_comment_recipient"
    assert calls == [
        ("122210969480562448_1704741537204014/private_replies", {"message": "Private answer"}),
        ("1704741537204014/private_replies", {"message": "Private answer"}),
        ("page_1/messages", {"recipient": {"comment_id": "122210969480562448_1704741537204014"}, "message": {"text": "Private answer"}}),
    ]


def test_private_reply_does_not_fallback_after_non_object_error(monkeypatch):
    calls = []

    def meta_call(method, path, token, params=None, data=None, app_secret=None):
        calls.append(path)
        raise webhooks.HTTPException(status_code=400, detail={"code": 10903, "message": "Cannot reply"})

    monkeypatch.setattr(webhooks, "meta_call", meta_call)

    with pytest.raises(webhooks.HTTPException):
        webhooks.send_facebook_private_reply({"page_id": "page_1", "comment_id": "comment_1"}, "Hello", "token")

    assert calls == ["comment_1/private_replies"]


def test_process_comment_events_uses_approved_alias(monkeypatch):
    processed = []
    logged = []
    event = {"page_id": "page_1", "post_id": "canonical_dark_post", "comment_id": "comment_1", "message": "hello"}
    rule = {"rule_id": "rule_1", "tenant_id": "tenant_1", "match_mode": "all_comments"}
    monkeypatch.setattr(webhooks, "extract_comment_events", lambda payload: [event])
    monkeypatch.setattr(webhooks, "list_enabled_comment_automation_rules_for_post", lambda page_id, post_id: [])
    monkeypatch.setattr(webhooks, "list_enabled_comment_automation_rules_for_alias", lambda page_id, post_id: [rule])
    monkeypatch.setattr(webhooks, "save_comment_webhook_event", lambda event, status, **kwargs: logged.append(status))
    monkeypatch.setattr(webhooks, "_process_rule", lambda rule, event: processed.append((rule, event)))

    webhooks.process_comment_events({})

    assert logged == ["processing"]
    assert processed == [(rule, event)]


def test_link_post_alias_requires_rule_and_canonical_post():
    with pytest.raises(ValidationError):
        CommentAutomationManageRequest(action="link_post_alias", page_id="page_1", rule_id="rule_1")

    request = CommentAutomationManageRequest(
        action="link_post_alias",
        page_id="page_1",
        post_id="canonical_dark_post",
        rule_id="rule_1",
    )
    assert request.post_id == "canonical_dark_post"
