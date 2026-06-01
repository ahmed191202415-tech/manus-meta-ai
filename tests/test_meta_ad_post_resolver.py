from app.core import meta_ad_post_resolver


def test_story_ids_match_accepts_exact_id_and_same_story_suffix():
    assert meta_ad_post_resolver.story_ids_match("page_1_story_1", ["page_1_story_1"]) is True
    assert meta_ad_post_resolver.story_ids_match("page_2_story_1", ["page_1_story_1"]) is True
    assert meta_ad_post_resolver.story_ids_match("page_2_story_2", ["page_1_story_1"]) is False


def test_fetch_verified_ad_story_scope_uses_meta_creative_story_ids(monkeypatch):
    monkeypatch.setattr(
        meta_ad_post_resolver,
        "meta_call",
        lambda *args, **kwargs: {
            "id": "ad_1",
            "name": "Lead ad",
            "creative": {
                "id": "creative_1",
                "name": "Creative",
                "object_story_id": "page_1_story_1",
                "effective_object_story_id": "page_2_story_1",
            },
        },
    )

    scope = meta_ad_post_resolver.fetch_verified_ad_story_scope("ad_1", "token")

    assert scope["ad_id"] == "ad_1"
    assert scope["creative_id"] == "creative_1"
    assert scope["trusted_post_ids"] == ["page_1_story_1", "page_2_story_1"]
