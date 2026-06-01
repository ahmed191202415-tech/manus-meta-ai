from app.core.meta_client import meta_call


def _clean(value) -> str:
    return str(value or "").strip()


def normalize_story_ids(*values) -> list[str]:
    story_ids: list[str] = []
    for value in values:
        if isinstance(value, (list, tuple, set)):
            candidates = value
        else:
            candidates = [value]
        for candidate in candidates:
            clean_candidate = _clean(candidate)
            if clean_candidate and clean_candidate not in story_ids:
                story_ids.append(clean_candidate)
    return story_ids


def story_ids_match(post_id: str, trusted_post_ids: list[str] | None) -> bool:
    clean_post_id = _clean(post_id)
    if not clean_post_id:
        return False
    post_suffix = clean_post_id.rsplit("_", 1)[-1]
    for trusted_post_id in normalize_story_ids(trusted_post_ids or []):
        if clean_post_id == trusted_post_id:
            return True
        if "_" in clean_post_id and "_" in trusted_post_id and post_suffix == trusted_post_id.rsplit("_", 1)[-1]:
            return True
    return False


def fetch_verified_ad_story_scope(ad_id: str, access_token: str, app_secret: str | None = None) -> dict:
    clean_ad_id = _clean(ad_id)
    payload = meta_call(
        "GET",
        clean_ad_id,
        access_token,
        params={
            "fields": (
                "id,name,creative{"
                "id,name,object_story_id,effective_object_story_id"
                "}"
            )
        },
        app_secret=app_secret,
    )
    creative = payload.get("creative") or {}
    trusted_post_ids = normalize_story_ids(
        creative.get("object_story_id"),
        creative.get("effective_object_story_id"),
    )
    return {
        "ad_id": _clean(payload.get("id")) or clean_ad_id,
        "ad_name": _clean(payload.get("name")),
        "creative_id": _clean(creative.get("id")),
        "creative_name": _clean(creative.get("name")),
        "effective_object_story_id": _clean(creative.get("effective_object_story_id")),
        "trusted_post_ids": trusted_post_ids,
    }
