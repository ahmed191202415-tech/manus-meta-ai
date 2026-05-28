import requests
from fastapi import HTTPException

from app.core.oauth_store import (
    get_active_clarity_connection_for_tenant,
    get_latest_clarity_connection,
)

CLARITY_EXPORT_URL = "https://www.clarity.ms/export-data/api/v1/project-live-insights"
ALLOWED_CLARITY_DIMENSIONS = {
    "Browser",
    "Device",
    "Country/Region",
    "OS",
    "Source",
    "Medium",
    "Campaign",
    "Channel",
    "URL",
}


def get_clarity_connection_or_401(tenant_id: str | None = None) -> dict:
    try:
        connection = get_active_clarity_connection_for_tenant(tenant_id) if tenant_id else get_latest_clarity_connection()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Clarity connection storage is not available: {exc}") from exc
    if not connection:
        raise HTTPException(status_code=401, detail="Microsoft Clarity is not connected for this tenant.")
    return connection


def run_clarity_live_insights(
    tenant_id: str | None,
    num_of_days: int = 1,
    dimensions: list[str] | None = None,
) -> dict:
    connection = get_clarity_connection_or_401(tenant_id)
    dims = _validate_dimensions(dimensions or [])
    params = {"numOfDays": str(min(max(int(num_of_days or 1), 1), 3))}
    for index, dimension in enumerate(dims[:3], start=1):
        params[f"dimension{index}"] = dimension
    response = requests.get(
        CLARITY_EXPORT_URL,
        headers={"Authorization": f"Bearer {connection['api_token']}", "Content-Type": "application/json"},
        params=params,
        timeout=45,
    )
    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=response.text) from exc
    if response.status_code >= 400:
        raise HTTPException(
            status_code=response.status_code,
            detail={"message": "Clarity data export failed.", "clarity_response": payload},
        )
    return {
        "tenant_id": connection.get("tenant_id"),
        "project_name": connection.get("project_name"),
        "num_of_days": params["numOfDays"],
        "dimensions": dims,
        "raw": payload,
    }


def _validate_dimensions(dimensions: list[str]) -> list[str]:
    invalid = [item for item in dimensions if item not in ALLOWED_CLARITY_DIMENSIONS]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail={"message": "Invalid Clarity dimension.", "invalid_dimensions": invalid, "allowed_dimensions": sorted(ALLOWED_CLARITY_DIMENSIONS)},
        )
    return dimensions
