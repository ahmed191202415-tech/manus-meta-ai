from __future__ import annotations

from typing import Any

from fastapi import HTTPException


def response_json(response, provider: str) -> Any:
    """Decode an upstream JSON response without leaking an HTML error page."""
    try:
        return response.json()
    except (TypeError, ValueError) as exc:
        body = str(getattr(response, "text", "") or "").strip()
        raise HTTPException(
            status_code=502,
            detail={
                "message": f"{provider} returned an invalid response.",
                "upstream_status": getattr(response, "status_code", None),
                "response_preview": body[:500],
            },
        ) from exc


def require_object(payload: Any, provider: str) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=502,
            detail={"message": f"{provider} returned an unexpected response shape."},
        )
    return payload

