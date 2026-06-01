import json
from typing import Any

from starlette.datastructures import MutableHeaders


SENSITIVE_KEYS = {
    "access_token",
    "refresh_token",
    "meta_access_token",
    "page_access_token",
    "selected_page_access_token",
    "appsecret_proof",
    "client_secret",
    "meta_app_secret",
}
HEAVY_KEYS = {
    "asset_feed_spec",
    "object_story_spec",
    "tracking_specs",
    "targeting",
    "raw",
    "raw_response",
}
PAGING_URL_KEYS = {"next", "previous"}


def _json_size(payload: Any) -> int:
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _omitted(value: Any, reason: str) -> dict[str, Any]:
    size = len(value) if isinstance(value, (dict, list, str)) else None
    result: dict[str, Any] = {"_omitted": True, "reason": reason}
    if size is not None:
        result["original_items"] = size
    return result


def sanitize_response_payload(
    value: Any,
    *,
    compact: bool = False,
    max_items: int = 50,
    depth: int = 0,
    path: str = "$",
    truncated_paths: list[str] | None = None,
) -> Any:
    truncated_paths = truncated_paths if truncated_paths is not None else []
    if depth > 7:
        truncated_paths.append(path)
        return _omitted(value, "maximum nesting depth reached")

    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            clean_key = str(key)
            child_path = f"{path}.{clean_key}"
            if clean_key.lower() in SENSITIVE_KEYS:
                result[clean_key] = "[redacted]"
                continue
            if clean_key.lower() in PAGING_URL_KEYS and isinstance(item, str):
                truncated_paths.append(child_path)
                result[clean_key] = "[omitted pagination URL; use cursors.after]"
                continue
            if compact and clean_key.lower() in HEAVY_KEYS and isinstance(item, (dict, list, str)):
                truncated_paths.append(child_path)
                result[clean_key] = _omitted(item, "large detail omitted; request the specific entity when needed")
                continue
            result[clean_key] = sanitize_response_payload(
                item,
                compact=compact,
                max_items=max_items,
                depth=depth + 1,
                path=child_path,
                truncated_paths=truncated_paths,
            )
        return result

    if isinstance(value, list):
        selected = value[:max_items] if compact else value
        result = [
            sanitize_response_payload(
                item,
                compact=compact,
                max_items=max_items,
                depth=depth + 1,
                path=f"{path}[{index}]",
                truncated_paths=truncated_paths,
            )
            for index, item in enumerate(selected)
        ]
        if compact and len(value) > max_items:
            truncated_paths.append(path)
            result.append({"_truncated_items": len(value) - max_items, "original_items": len(value)})
        return result

    if isinstance(value, str) and compact and len(value) > 2000:
        truncated_paths.append(path)
        return value[:2000] + "... [truncated]"

    return value


def guard_json_bytes(body: bytes, max_bytes: int) -> bytes:
    try:
        payload = json.loads(body)
    except (TypeError, ValueError):
        return body

    original_bytes = len(body)
    redacted_paths: list[str] = []
    sanitized = sanitize_response_payload(payload, truncated_paths=redacted_paths)
    sanitized_bytes = _json_size(sanitized)
    if sanitized_bytes <= max_bytes:
        return json.dumps(sanitized, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    compacted = sanitized
    truncated_paths: list[str] = []
    for max_items in (50, 25, 10, 5):
        truncated_paths = []
        compacted = sanitize_response_payload(
            payload,
            compact=True,
            max_items=max_items,
            truncated_paths=truncated_paths,
        )
        if _json_size(compacted) <= max_bytes:
            break

    guard = {
        "compacted": True,
        "original_bytes": original_bytes,
        "returned_bytes_before_notice": _json_size(compacted),
        "truncated_paths": sorted(set(truncated_paths))[:100],
        "hint": "Request a smaller limit or open one specific campaign, ad set, ad, creative, page, or date range for details.",
    }
    if isinstance(compacted, dict):
        compacted["_response_guard"] = guard
    else:
        compacted = {"data": compacted, "_response_guard": guard}
    return json.dumps(compacted, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class ResponseGuardMiddleware:
    def __init__(self, app, max_bytes: int, guarded_paths: set[str]):
        self.app = app
        self.max_bytes = max(50_000, int(max_bytes))
        self.guarded_paths = guarded_paths

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") not in self.guarded_paths:
            await self.app(scope, receive, send)
            return

        start_message = None
        body_parts: list[bytes] = []

        async def capture_send(message):
            nonlocal start_message
            if message["type"] == "http.response.start":
                start_message = message
                return
            if message["type"] != "http.response.body":
                await send(message)
                return
            body_parts.append(message.get("body", b""))
            if message.get("more_body", False):
                return

            body = b"".join(body_parts)
            headers = MutableHeaders(raw=(start_message or {}).get("headers", []))
            if "application/json" in headers.get("content-type", ""):
                body = guard_json_bytes(body, self.max_bytes)
                headers["content-length"] = str(len(body))
            if start_message is None:
                start = {"type": "http.response.start", "status": 200, "headers": headers.raw}
            else:
                start = {**start_message, "headers": headers.raw}
            await send(start)
            await send({"type": "http.response.body", "body": body, "more_body": False})

        await self.app(scope, receive, capture_send)
