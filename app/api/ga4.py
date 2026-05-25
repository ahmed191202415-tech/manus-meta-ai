from fastapi import APIRouter, HTTPException, Query, Request

from app.core.ga4_client import list_ga4_properties
from app.core.oauth_store import (
    get_active_google_connection_for_tenant,
    update_selected_ga4_property,
)
from app.schemas.ga4_requests import GA4PropertySelectionRequest

router = APIRouter(prefix="/ga4", tags=["ga4"])


def _resolve_tenant_id(request: Request, tenant_id: str | None = None) -> str:
    resolved = str(tenant_id or request.session.get("tenant_id") or "").strip()
    if not resolved:
        raise HTTPException(status_code=401, detail="Tenant is required for GA4 requests.")
    return resolved


def _get_google_connection_or_storage_error(tenant_id: str) -> dict | None:
    try:
        return get_active_google_connection_for_tenant(tenant_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Google connection storage is not available: {exc}") from exc


@router.get("/properties")
async def ga4_properties(request: Request, tenant_id: str | None = Query(default=None)):
    resolved_tenant_id = _resolve_tenant_id(request, tenant_id)
    properties = list_ga4_properties(resolved_tenant_id)
    connection = _get_google_connection_or_storage_error(resolved_tenant_id)
    return {
        "tenant_id": resolved_tenant_id,
        "selected_property": {
            "property_id": connection.get("selected_ga4_property_id") if connection else None,
            "property_name": connection.get("selected_ga4_property_name") if connection else None,
        },
        "properties": properties,
    }


@router.post("/select_property")
async def ga4_select_property(body: GA4PropertySelectionRequest, request: Request):
    resolved_tenant_id = _resolve_tenant_id(request, body.tenant_id)
    connection = _get_google_connection_or_storage_error(resolved_tenant_id)
    if not connection:
        raise HTTPException(status_code=401, detail="Google is not connected for this tenant.")
    updated = update_selected_ga4_property(
        resolved_tenant_id,
        body.property_id,
        body.property_name,
    )
    return {
        "success": True,
        "tenant_id": resolved_tenant_id,
        "selected_property": {
            "property_id": (updated or {}).get("selected_ga4_property_id") or body.property_id,
            "property_name": (updated or {}).get("selected_ga4_property_name") or body.property_name,
        },
    }
