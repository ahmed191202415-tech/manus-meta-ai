from datetime import date, datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException

from app.config import DEFAULT_PAGE_LIMIT, DEFAULT_MAX_PAGES
from app.core.auth import resolve_access_token
from app.core.pagination import meta_get_all_pages
from app.core.meta_client import meta_call, normalize_account_id
from app.schemas.meta_requests import PixelCreateRequest, PixelEventCatalogRequest

router = APIRouter(tags=["pixels"])


@router.get("/pixels")
async def list_pixels(
    account_id: str,
    fields: str = "id,name,code,last_fired_time,creation_time,owner_ad_account,event_stats,enable_automatic_matching",
    limit: int = DEFAULT_PAGE_LIMIT,
    after: Optional[str] = None,
    fetch_all: bool = False,
    max_pages: int = DEFAULT_MAX_PAGES,
    token: str = Depends(resolve_access_token),
):
    account_id = normalize_account_id(account_id)
    params = {"fields": fields, "limit": limit}
    if after:
        params["after"] = after
    if fetch_all:
        return meta_get_all_pages(f"{account_id}/adspixels", token, params=params, max_pages=max_pages)
    return meta_call("GET", f"{account_id}/adspixels", token, params=params)


@router.post("/pixels")
async def create_pixel(body: PixelCreateRequest, token: str = Depends(resolve_access_token)):
    account_id = normalize_account_id(body.account_id)
    payload = {"name": body.name}
    payload.update(body.extra_params)
    return meta_call("POST", f"{account_id}/adspixels", token, data=payload)


@router.post("/pixel_events/catalog")
async def pixel_event_catalog(body: PixelEventCatalogRequest, token: str = Depends(resolve_access_token)):
    requested_start, requested_end = _catalog_date_range(body.start_date, body.end_date, body.fallback_days)
    attempts = []
    events, raw_rows = _fetch_pixel_event_counts(body.pixel_id, token, requested_start, requested_end)
    attempts.append(_attempt_summary(requested_start, requested_end, raw_rows, events))

    fallback_used = False
    fallback_start = requested_end - timedelta(days=body.fallback_days - 1)
    if not events and fallback_start < requested_start:
        fallback_used = True
        events, raw_rows = _fetch_pixel_event_counts(body.pixel_id, token, fallback_start, requested_end)
        attempts.append(_attempt_summary(fallback_start, requested_end, raw_rows, events))

    response = {
        "source": "meta_pixel_stats",
        "pixel_id": body.pixel_id,
        "aggregation": "event_total_counts",
        "event_names": [item["event_name"] for item in events],
        "events": events,
        "event_count": len(events),
        "fallback_used": fallback_used,
        "attempts": attempts,
        "limits": (
            []
            if events
            else [
                "Meta returned no named received events from Pixel stats for the inspected range.",
                "Custom Conversions are configuration objects and are not a substitute for received Pixel event names.",
            ]
        ),
    }
    if body.include_raw:
        response["raw_rows"] = raw_rows
    return response


def _catalog_date_range(start_date: str | None, end_date: str | None, default_days: int) -> tuple[date, date]:
    today = date.today()
    parsed_end = _parse_date(end_date, "end_date") if end_date else today
    parsed_start = _parse_date(start_date, "start_date") if start_date else parsed_end - timedelta(days=default_days - 1)
    if parsed_start > parsed_end:
        raise HTTPException(status_code=422, detail="start_date must not be after end_date.")
    return parsed_start, parsed_end


def _parse_date(value: str, field_name: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{field_name} must use YYYY-MM-DD format.") from exc


def _fetch_pixel_event_counts(pixel_id: str, token: str, start_date: date, end_date: date) -> tuple[list[dict], list[dict]]:
    payload = meta_call(
        "GET",
        f"{pixel_id}/stats",
        token,
        params={
            "aggregation": "event_total_counts",
            "start_time": start_date.isoformat(),
            # Meta treats the upper timestamp as a boundary. Add one day so the selected end date is included.
            "end_time": (end_date + timedelta(days=1)).isoformat(),
        },
    )
    raw_rows = payload.get("data", []) if isinstance(payload, dict) else []
    return _normalize_pixel_event_counts(raw_rows), raw_rows


def _normalize_pixel_event_counts(rows: list[dict]) -> list[dict]:
    counts: dict[str, float] = {}
    for row in rows:
        _collect_event_counts(row.get("data") if isinstance(row, dict) else row, counts)
    return [
        {"event_name": event_name, "count": int(count) if count.is_integer() else count}
        for event_name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0].casefold()))
    ]


def _collect_event_counts(value: Any, counts: dict[str, float]) -> None:
    if isinstance(value, dict):
        event_name = _first_text(value, "event_name", "event", "name", "key")
        count = _first_number(value, "count", "event_count", "value", "total")
        if event_name and count is not None:
            counts[event_name] = counts.get(event_name, 0.0) + count
            return
        for key, nested in value.items():
            if isinstance(nested, (int, float)) and not isinstance(nested, bool) and _looks_like_event_name(key):
                counts[str(key)] = counts.get(str(key), 0.0) + float(nested)
            else:
                _collect_event_counts(nested, counts)
        return
    if isinstance(value, list):
        if len(value) == 2 and isinstance(value[0], str) and isinstance(value[1], (int, float)) and not isinstance(value[1], bool):
            counts[value[0]] = counts.get(value[0], 0.0) + float(value[1])
            return
        for nested in value:
            _collect_event_counts(nested, counts)


def _first_text(value: dict, *keys: str) -> str | None:
    for key in keys:
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def _first_number(value: dict, *keys: str) -> float | None:
    for key in keys:
        candidate = value.get(key)
        if isinstance(candidate, (int, float)) and not isinstance(candidate, bool):
            return float(candidate)
        if isinstance(candidate, str):
            try:
                return float(candidate)
            except ValueError:
                continue
    return None


def _looks_like_event_name(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text) and text not in {"aggregation", "start_time", "data"}


def _attempt_summary(start_date: date, end_date: date, rows: list[dict], events: list[dict]) -> dict:
    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "raw_row_count": len(rows),
        "named_event_count": len(events),
    }
