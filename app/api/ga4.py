from html import escape

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from app.analytics.ga4_preprocessing import normalize_ga4_report
from app.analytics.custom_report_engine import build_custom_report_output, validate_ga4_report_request
from app.core.ga4_client import (
    get_ga4_metadata,
    list_ga4_properties,
    run_ga4_funnel_report,
    run_ga4_realtime_report,
    run_ga4_report,
)
from app.core.oauth_store import (
    get_active_google_connection_for_tenant,
    update_selected_ga4_property,
)
from app.core.tenant_resolver import resolve_tenant_id_for_google
from app.schemas.ga4_requests import (
    GA4CustomReportRequest,
    GA4DateRangeRequest,
    GA4FunnelReportRequest,
    GA4PropertySelectionRequest,
)

router = APIRouter(prefix="/ga4", tags=["ga4"])


def _resolve_tenant_id(request: Request, tenant_id: str | None = None) -> str:
    return resolve_tenant_id_for_google(request, tenant_id)


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


@router.get("/select_property_link", response_class=HTMLResponse, include_in_schema=False)
async def ga4_select_property_link(
    request: Request,
    tenant_id: str | None = Query(default=None),
    property_id: str = Query(min_length=1),
    property_name: str | None = Query(default=None),
):
    resolved_tenant_id = _resolve_tenant_id(request, tenant_id)
    connection = _get_google_connection_or_storage_error(resolved_tenant_id)
    if not connection:
        raise HTTPException(status_code=401, detail="Google is not connected for this tenant.")
    selected_name = property_name or property_id
    update_selected_ga4_property(resolved_tenant_id, property_id, selected_name)
    safe_tenant_id = escape(resolved_tenant_id)
    safe_property_id = escape(property_id)
    safe_property_name = escape(selected_name)
    return f"""
    <!doctype html>
    <html lang="ar" dir="rtl">
      <head>
        <meta charset="utf-8" />
        <title>تم اختيار Google Analytics</title>
        <style>
          body {{ font-family: Arial, sans-serif; margin: 40px; line-height: 1.7; }}
          code {{ background: #f4f4f4; padding: 2px 6px; border-radius: 4px; }}
        </style>
      </head>
      <body>
        <h1>تم اختيار Google Analytics بنجاح</h1>
        <p>العميل: <code>{safe_tenant_id}</code></p>
        <p>Property: <code>{safe_property_id}</code> - {safe_property_name}</p>
        <p>تقدر الآن تستخدم GPT لتحليل الموقع من endpoint <code>/website/analyze</code>.</p>
      </body>
    </html>
    """


def _with_rows(payload: dict) -> dict:
    return {**payload, "normalized_rows": normalize_ga4_report(payload)}


@router.post("/custom_report")
async def ga4_custom_report(body: GA4CustomReportRequest, request: Request):
    tenant_id = _resolve_tenant_id(request, body.tenant_id)
    validation = validate_ga4_report_request(body.dimensions, body.metrics, body.limit)
    payload = run_ga4_report(
        tenant_id=tenant_id,
        property_id=body.property_id,
        dimensions=body.dimensions,
        metrics=body.metrics,
        start_date=body.start_date,
        end_date=body.end_date,
        limit=body.limit,
        filters=body.filters,
        order_by=body.order_by,
        offset=body.offset,
        metric_aggregations=body.metric_aggregations,
    )
    normalized_rows = normalize_ga4_report(payload)
    return build_custom_report_output(payload, normalized_rows, validation)


@router.post("/report")
async def ga4_report(body: GA4CustomReportRequest, request: Request):
    return await ga4_custom_report(body, request)


@router.post("/funnel")
async def ga4_funnel(body: GA4FunnelReportRequest, request: Request):
    tenant_id = _resolve_tenant_id(request, body.tenant_id)
    return run_ga4_funnel_report(
        tenant_id=tenant_id,
        property_id=body.property_id,
        steps=[step.model_dump() for step in body.steps],
        start_date=body.start_date,
        end_date=body.end_date,
    )


@router.get("/realtime")
async def ga4_realtime(
    request: Request,
    tenant_id: str | None = Query(default=None),
    property_id: str | None = Query(default=None),
    dimensions: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
):
    resolved_tenant_id = _resolve_tenant_id(request, tenant_id)
    dims = [item.strip() for item in dimensions.split(",") if item.strip()] if dimensions else None
    return _with_rows(run_ga4_realtime_report(resolved_tenant_id, property_id, dimensions=dims, limit=limit))


@router.get("/metadata")
async def ga4_metadata(
    request: Request,
    tenant_id: str | None = Query(default=None),
    property_id: str | None = Query(default=None),
):
    return get_ga4_metadata(_resolve_tenant_id(request, tenant_id), property_id)


@router.get("/landing_pages")
async def ga4_landing_pages(
    request: Request,
    tenant_id: str | None = Query(default=None),
    property_id: str | None = Query(default=None),
    start_date: str = "30daysAgo",
    end_date: str = "today",
    limit: int = Query(default=100, ge=1, le=1000),
):
    payload = run_ga4_report(
        _resolve_tenant_id(request, tenant_id),
        property_id,
        ["landingPagePlusQueryString", "sessionSourceMedium", "deviceCategory"],
        ["sessions", "activeUsers", "engagedSessions", "engagementRate", "averageSessionDuration", "conversions", "totalRevenue"],
        start_date,
        end_date,
        limit,
    )
    return _with_rows(payload)


@router.get("/traffic_sources")
async def ga4_traffic_sources(
    request: Request,
    tenant_id: str | None = Query(default=None),
    property_id: str | None = Query(default=None),
    start_date: str = "30daysAgo",
    end_date: str = "today",
    limit: int = Query(default=100, ge=1, le=1000),
):
    payload = run_ga4_report(
        _resolve_tenant_id(request, tenant_id),
        property_id,
        ["sessionSourceMedium", "sessionCampaignName", "date"],
        ["sessions", "activeUsers", "engagedSessions", "engagementRate", "conversions", "totalRevenue"],
        start_date,
        end_date,
        limit,
    )
    return _with_rows(payload)


@router.get("/events")
async def ga4_events(
    request: Request,
    tenant_id: str | None = Query(default=None),
    property_id: str | None = Query(default=None),
    start_date: str = "30daysAgo",
    end_date: str = "today",
    limit: int = Query(default=100, ge=1, le=1000),
):
    payload = run_ga4_report(
        _resolve_tenant_id(request, tenant_id),
        property_id,
        ["eventName", "date"],
        ["eventCount", "activeUsers"],
        start_date,
        end_date,
        limit,
    )
    return _with_rows(payload)


@router.get("/devices")
async def ga4_devices(
    request: Request,
    tenant_id: str | None = Query(default=None),
    property_id: str | None = Query(default=None),
    start_date: str = "30daysAgo",
    end_date: str = "today",
    limit: int = Query(default=100, ge=1, le=1000),
):
    payload = run_ga4_report(
        _resolve_tenant_id(request, tenant_id),
        property_id,
        ["deviceCategory", "sessionSourceMedium"],
        ["sessions", "engagedSessions", "engagementRate", "conversions", "totalRevenue"],
        start_date,
        end_date,
        limit,
    )
    return _with_rows(payload)
