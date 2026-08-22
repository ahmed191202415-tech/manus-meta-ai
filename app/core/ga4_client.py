from datetime import datetime, timedelta, timezone
import requests
from fastapi import HTTPException

from app.core.google_oauth import get_google_service_account_token, refresh_google_access_token
from app.core.external_http import require_object, response_json
from app.core.ga4_requests import (
    build_funnel_request,
    build_report_request,
    dimension as _dimension,
    metric as _metric,
    normalize_ga4_filters,
    normalize_ga4_order_bys,
)
from app.core.oauth_store import (
    get_active_google_connection_for_tenant,
    update_google_tokens,
)

GA4_ADMIN_ACCOUNT_SUMMARIES_URL = "https://analyticsadmin.googleapis.com/v1beta/accountSummaries"
GA4_DATA_BASE_URL = "https://analyticsdata.googleapis.com/v1beta"
def _parse_dt(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_expiring(expires_at: str | None) -> bool:
    parsed = _parse_dt(expires_at)
    if not parsed:
        return False
    return parsed <= datetime.now(timezone.utc) + timedelta(minutes=5)


def get_google_connection_or_401(tenant_id: str) -> dict:
    try:
        connection = get_active_google_connection_for_tenant(tenant_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Google connection storage is not available: {exc}") from exc
    if not connection:
        raise HTTPException(status_code=401, detail="Google is not connected for this tenant.")
    return connection


def get_google_credentials_for_tenant(tenant_id: str) -> dict:
    connection = get_google_connection_or_401(tenant_id)
    if connection.get("connection_mode") == "service_account":
        refreshed = get_google_service_account_token()
        updated = update_google_tokens(tenant_id, refreshed)
        return {**connection, **refreshed, **(updated or {})}
    if _is_expiring(connection.get("expires_at")):
        refreshed = refresh_google_access_token(connection.get("refresh_token") or "")
        updated = update_google_tokens(tenant_id, refreshed)
        if updated:
            connection = {**connection, **updated}
        else:
            connection = {**connection, **refreshed}
    return connection


def _auth_headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}


def resolve_ga4_property_id(tenant_id: str, property_id: str | None = None) -> str:
    if property_id:
        return str(property_id).replace("properties/", "").strip()
    connection = get_google_connection_or_401(tenant_id)
    selected = str(connection.get("selected_ga4_property_id") or "").replace("properties/", "").strip()
    if not selected:
        properties = []
        try:
            properties = list_ga4_properties(tenant_id)
        except Exception:
            properties = []
        if len(properties) == 1:
            return str(properties[0].get("property_id") or properties[0].get("property") or "").replace("properties/", "").strip()
        raise HTTPException(
            status_code=400,
            detail={
                "message": "GA4 property not selected. Pass property_id or select a property first.",
                "reason": "property_selection_required",
                "available_properties": properties[:25],
                "next_step": "Use /tools/ga4 action=list_properties, then retry with property_id or action=select_property.",
            },
        )
    return selected


def list_ga4_properties(tenant_id: str) -> list[dict]:
    credentials = get_google_credentials_for_tenant(tenant_id)
    response = requests.get(
        GA4_ADMIN_ACCOUNT_SUMMARIES_URL,
        headers=_auth_headers(credentials["access_token"]),
        timeout=30,
    )
    data = require_object(response_json(response, "GA4 Admin API"), "GA4 Admin API")
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail={"message": "Could not list GA4 properties.", "google_response": data})

    properties = []
    for account in data.get("accountSummaries", []):
        account_name = account.get("displayName")
        account_resource = account.get("account")
        for prop in account.get("propertySummaries", []):
            resource_name = prop.get("property") or ""
            property_id = resource_name.split("/")[-1] if "/" in resource_name else resource_name
            properties.append(
                {
                    "account": account_resource,
                    "account_name": account_name,
                    "property": resource_name,
                    "property_id": property_id,
                    "property_name": prop.get("displayName"),
                    "property_type": prop.get("propertyType"),
                    "parent": prop.get("parent"),
                }
            )
    return properties


def run_ga4_report(
    tenant_id: str,
    property_id: str | None,
    dimensions: list[str],
    metrics: list[str],
    start_date: str = "30daysAgo",
    end_date: str = "today",
    limit: int = 100,
    filters: dict | None = None,
    order_by: list[dict] | None = None,
    offset: int = 0,
    metric_aggregations: list[str] | None = None,
) -> dict:
    resolved_property_id = resolve_ga4_property_id(tenant_id, property_id)
    credentials = get_google_credentials_for_tenant(tenant_id)
    body = build_report_request(
        dimensions, metrics, start_date, end_date, limit, offset, filters, order_by, metric_aggregations
    )
    response = requests.post(
        f"{GA4_DATA_BASE_URL}/properties/{resolved_property_id}:runReport",
        headers=_auth_headers(credentials["access_token"]),
        json=body,
        timeout=45,
    )
    data = require_object(response_json(response, "GA4 Data API"), "GA4 Data API")
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail={"message": "GA4 report failed.", "google_response": data})
    data["property_id"] = resolved_property_id
    data["date_range"] = {"start_date": start_date, "end_date": end_date}
    return data


def run_ga4_funnel_report(
    tenant_id: str,
    property_id: str | None,
    steps: list[dict],
    start_date: str = "30daysAgo",
    end_date: str = "today",
) -> dict:
    resolved_property_id = resolve_ga4_property_id(tenant_id, property_id)
    credentials = get_google_credentials_for_tenant(tenant_id)
    body = build_funnel_request(steps, start_date, end_date)
    response = requests.post(
        f"https://analyticsdata.googleapis.com/v1alpha/properties/{resolved_property_id}:runFunnelReport",
        headers=_auth_headers(credentials["access_token"]),
        json=body,
        timeout=45,
    )
    data = require_object(response_json(response, "GA4 Funnel API"), "GA4 Funnel API")
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail={"message": "GA4 funnel report failed.", "google_response": data})
    data["property_id"] = resolved_property_id
    return data


def run_ga4_realtime_report(
    tenant_id: str,
    property_id: str | None,
    dimensions: list[str] | None = None,
    metrics: list[str] | None = None,
    limit: int = 100,
) -> dict:
    resolved_property_id = resolve_ga4_property_id(tenant_id, property_id)
    credentials = get_google_credentials_for_tenant(tenant_id)
    body = {
        "dimensions": [_dimension(item) for item in (dimensions or ["country", "deviceCategory"])],
        "metrics": [_metric(item) for item in (metrics or ["activeUsers"])],
        "limit": str(min(max(int(limit or 100), 1), 1000)),
    }
    response = requests.post(
        f"{GA4_DATA_BASE_URL}/properties/{resolved_property_id}:runRealtimeReport",
        headers=_auth_headers(credentials["access_token"]),
        json=body,
        timeout=45,
    )
    data = require_object(response_json(response, "GA4 Realtime API"), "GA4 Realtime API")
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail={"message": "GA4 realtime report failed.", "google_response": data})
    data["property_id"] = resolved_property_id
    return data


def get_ga4_metadata(tenant_id: str, property_id: str | None = None) -> dict:
    resolved_property_id = resolve_ga4_property_id(tenant_id, property_id)
    credentials = get_google_credentials_for_tenant(tenant_id)
    response = requests.get(
        f"{GA4_DATA_BASE_URL}/properties/{resolved_property_id}/metadata",
        headers=_auth_headers(credentials["access_token"]),
        timeout=45,
    )
    data = require_object(response_json(response, "GA4 Metadata API"), "GA4 Metadata API")
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail={"message": "GA4 metadata failed.", "google_response": data})
    data["property_id"] = resolved_property_id
    return data
