import requests
from fastapi import HTTPException
from requests import Response

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
    payload = _response_payload(response)
    if response.status_code >= 400:
        raise HTTPException(
            status_code=response.status_code,
            detail={
                "message": "Clarity data export failed.",
                "status_code": response.status_code,
                "reason": response.reason,
                "request_params": params,
                "clarity_response": payload,
                "hints": _clarity_error_hints(response.status_code),
            },
        )
    return {
        "tenant_id": connection.get("tenant_id"),
        "project_name": connection.get("project_name"),
        "num_of_days": params["numOfDays"],
        "dimensions": dims,
        "raw": payload,
    }


def run_clarity_live_insights_with_fallbacks(
    tenant_id: str | None,
    num_of_days: int = 1,
    dimensions: list[str] | None = None,
) -> dict:
    attempts = []
    dims = dimensions or []
    if dims:
        attempts.append(dims[:3])
    if dims != ["URL"]:
        attempts.append(["URL"])
    attempts.append([])

    errors = []
    for attempt in attempts:
        try:
            result = run_clarity_live_insights(tenant_id, num_of_days, attempt)
            result["fallback_used"] = attempt != dims[:3]
            result["attempted_dimensions"] = attempts
            result["fallback_errors"] = errors
            return result
        except HTTPException as exc:
            errors.append(exc.detail)
    raise HTTPException(
        status_code=502,
        detail={
            "message": "Clarity data export failed for all dimension attempts.",
            "attempted_dimensions": attempts,
            "errors": errors,
        },
    )


def _response_payload(response: Response):
    try:
        return response.json()
    except ValueError:
        text = response.text.strip()
        return {"raw_text": text, "empty_body": not bool(text)}


def _clarity_error_hints(status_code: int) -> list[str]:
    if status_code == 400:
        return ["Try fewer dimensions, for example URL only.", "numOfDays must be 1, 2, or 3."]
    if status_code == 401:
        return ["The Clarity API token is missing, invalid, or expired. Re-generate it from Settings > Data Export."]
    if status_code == 403:
        return ["The token is not authorized for this Clarity project. Generate the token as a project admin."]
    if status_code == 429:
        return ["Clarity allows about 10 API requests per project per day. Wait or reduce repeated calls."]
    return ["Try a simpler request with URL only, then retry behavior audit."]


def _validate_dimensions(dimensions: list[str]) -> list[str]:
    invalid = [item for item in dimensions if item not in ALLOWED_CLARITY_DIMENSIONS]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail={"message": "Invalid Clarity dimension.", "invalid_dimensions": invalid, "allowed_dimensions": sorted(ALLOWED_CLARITY_DIMENSIONS)},
        )
    return dimensions
