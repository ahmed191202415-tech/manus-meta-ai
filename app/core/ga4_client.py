from datetime import datetime, timedelta, timezone

import requests
from fastapi import HTTPException

from app.core.google_oauth import refresh_google_access_token
from app.core.oauth_store import (
    get_active_google_connection_for_tenant,
    update_google_tokens,
)

GA4_ADMIN_ACCOUNT_SUMMARIES_URL = "https://analyticsadmin.googleapis.com/v1beta/accountSummaries"


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
    if _is_expiring(connection.get("expires_at")):
        refreshed = refresh_google_access_token(connection.get("refresh_token") or "")
        updated = update_google_tokens(tenant_id, refreshed)
        if updated:
            connection = {**connection, **updated}
        else:
            connection = {**connection, **refreshed}
    return connection


def _auth_headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


def list_ga4_properties(tenant_id: str) -> list[dict]:
    credentials = get_google_credentials_for_tenant(tenant_id)
    response = requests.get(
        GA4_ADMIN_ACCOUNT_SUMMARIES_URL,
        headers=_auth_headers(credentials["access_token"]),
        timeout=30,
    )
    data = response.json()
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


def run_ga4_report(*args, **kwargs):
    raise HTTPException(status_code=501, detail="GA4 report execution will be added in Phase 2.")


def run_ga4_funnel_report(*args, **kwargs):
    raise HTTPException(status_code=501, detail="GA4 funnel reports will be added in Phase 2.")


def run_ga4_realtime_report(*args, **kwargs):
    raise HTTPException(status_code=501, detail="GA4 realtime reports will be added in Phase 2.")


def get_ga4_metadata(*args, **kwargs):
    raise HTTPException(status_code=501, detail="GA4 metadata will be added in Phase 2.")
