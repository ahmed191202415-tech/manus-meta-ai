import hashlib
import hmac

from app.api import webhooks


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
            "POST",
            "page_1/private_replies",
            "page_token",
            {"object_id": "comment_1", "message": "Private answer"},
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
        "list_enabled_comment_automation_rules_for_post",
        lambda page_id, post_id: [{"tenant_id": "tenant_1"}],
    )
    monkeypatch.setattr(webhooks, "get_tenant_meta_app", lambda tenant_id: {"meta_app_secret": "tenant-secret"})

    assert webhooks.is_valid_meta_webhook_signature(
        payload,
        f"sha256={digest}",
        [{"page_id": "page_1", "post_id": "post_1"}],
    ) is True
