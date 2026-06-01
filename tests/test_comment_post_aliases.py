from app.core import oauth_store


def test_unmapped_posts_include_legacy_no_rule_status(monkeypatch):
    captured = {}

    def get_many(table, params=None):
        if table == "comment_webhook_events":
            captured.update(params or {})
            return [{"page_id": "page_1", "post_id": "canonical_post", "delivery_status": "no_rule_for_post"}]
        if table == "comment_post_aliases":
            return []
        raise AssertionError(table)

    monkeypatch.setattr(oauth_store, "_get_many", get_many)

    result = oauth_store.list_unmapped_comment_posts("tenant_1", page_id="page_1")

    assert captured["delivery_status"] == "in.(unmapped_ad_post,no_rule_for_post)"
    assert result[0]["post_id"] == "canonical_post"
