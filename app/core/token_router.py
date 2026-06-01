from typing import Any, Dict, Optional

from fastapi import HTTPException

from app.core.meta_client import meta_call
from app.core.oauth_store import find_meta_connection_by_access_token


def _first_path_segment(path: str) -> str:
    clean_path = str(path or "").strip().strip("/")
    if not clean_path:
        return ""
    return clean_path.split("/", 1)[0]


def _list_page_entries(user_token: str) -> list[dict[str, str]]:
    payload = meta_call(
        "GET",
        "me/accounts",
        user_token,
        params={"fields": "id,name,access_token", "limit": 200},
    )

    entries: list[dict[str, str]] = []
    for item in payload.get("data", []):
        page_id = str(item.get("id") or "").strip()
        page_token = str(item.get("access_token") or "").strip()
        if page_id and page_token:
            entries.append(
                {
                    "id": page_id,
                    "name": str(item.get("name") or "").strip(),
                    "access_token": page_token,
                }
            )
    return entries


def resolve_page_token_for_page_id(user_token: str, page_id: str) -> str:
    clean_page_id = str(page_id or "").strip()
    if not clean_page_id:
        return user_token

    connection = find_meta_connection_by_access_token(user_token)
    if (
        connection
        and str(connection.get("selected_page_id") or "").strip() == clean_page_id
        and str(connection.get("selected_page_access_token") or "").strip()
    ):
        return str(connection["selected_page_access_token"]).strip()

    try:
        page_entries = _list_page_entries(user_token)
    except HTTPException as exc:
        raise HTTPException(
            status_code=403,
            detail=(
                "A Page access token is required. Reconnect Meta after granting the Page permissions, "
                "then select or subscribe the Facebook Page before reading posts or comments."
            ),
        ) from exc

    for item in page_entries:
        if item["id"] == clean_page_id:
            return item["access_token"]

    raise HTTPException(
        status_code=403,
        detail=(
            f"No Page access token is available for Page {clean_page_id}. "
            "Reconnect Meta with a Facebook account that manages this Page, then select or subscribe the Page."
        ),
    )


def _resolve_page_id_for_form_id(user_token: str, form_id: str) -> Optional[str]:
    clean_form_id = str(form_id or "").strip()
    if not clean_form_id:
        return None

    try:
        payload = meta_call("GET", clean_form_id, user_token, params={"fields": "page_id"})
    except HTTPException:
        return None

    page_id = payload.get("page_id")
    if page_id:
        return str(page_id).strip()
    return None


def resolve_page_token_for_form_id(user_token: str, form_id: str) -> str:
    page_id = _resolve_page_id_for_form_id(user_token, form_id)
    if not page_id:
        return user_token
    return resolve_page_token_for_page_id(user_token, page_id)


def choose_token_for_meta_path(
    user_token: str,
    path: str,
    method: str,
    params: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
) -> str:
    del method, params, data

    clean_path = str(path or "").strip().strip("/")
    if not clean_path:
        return user_token

    if clean_path.endswith("/leadgen_forms"):
        page_id = _first_path_segment(clean_path)
        return resolve_page_token_for_page_id(user_token, page_id)

    if clean_path.endswith("/leads"):
        form_id = _first_path_segment(clean_path)
        return resolve_page_token_for_form_id(user_token, form_id)

    page_scoped_edges = (
        "/feed",
        "/posts",
        "/comments",
        "/insights",
    )
    if any(clean_path.endswith(edge) for edge in page_scoped_edges):
        page_id = _first_path_segment(clean_path)
        return resolve_page_token_for_page_id(user_token, page_id)

    return user_token
