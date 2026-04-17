from typing import Optional, Dict, Any, List

from app.config import DEFAULT_MAX_PAGES
from app.core.meta_client import meta_call


def meta_get_all_pages(path: str, access_token: str, params: Optional[Dict[str, Any]] = None, max_pages: int = DEFAULT_MAX_PAGES) -> Dict[str, Any]:
    params = dict(params or {})
    rows: List[Any] = []
    after: Optional[str] = None
    pages_fetched = 0
    last_payload: Dict[str, Any] = {}
    while pages_fetched < max_pages:
        page_params = dict(params)
        if after:
            page_params["after"] = after
        payload = meta_call("GET", path, access_token, params=page_params)
        last_payload = payload
        pages_fetched += 1
        data = payload.get("data")
        if not isinstance(data, list):
            return payload
        rows.extend(data)
        paging = payload.get("paging", {})
        cursors = paging.get("cursors", {})
        after = cursors.get("after")
        if not paging.get("next") or not after:
            break
    result = dict(last_payload)
    result["data"] = rows
    result["pages_fetched"] = pages_fetched
    result["truncated"] = pages_fetched >= max_pages and bool(last_payload.get("paging", {}).get("next"))
    return result