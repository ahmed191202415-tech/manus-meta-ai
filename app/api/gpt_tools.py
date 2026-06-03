from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ValidationError

from app.api import clarity, ga4, journey, leadgen, pixels, reports, website_analysis
from app.core.auth import resolve_access_token
from app.core.meta_client import meta_call, normalize_account_id
from app.core.token_router import resolve_page_token_for_page_id
from app.schemas.clarity_requests import ClarityBehaviorAuditRequest, ClarityRequest
from app.schemas.ga4_requests import (
    GA4CustomReportRequest,
    GA4DateRangeRequest,
    GA4FunnelReportRequest,
    GA4PropertySelectionRequest,
    JourneyAnalysisRequest,
    JourneyPayloadAnalysisRequest,
    MetaTrackingAuditRequest,
    WebsiteAnalysisRequest,
)
from app.schemas.gpt_tool_requests import (
    ClarityToolRequest,
    GA4ToolRequest,
    JourneyToolRequest,
    MetaTrackingToolRequest,
    ReportToolRequest,
    WebsiteToolRequest,
)
from app.schemas.meta_requests import PixelEventCatalogRequest
from app.schemas.report_requests import (
    IntelligenceReportRequest,
    SaveDocxReportRequest,
    SaveExcelReportRequest,
    SaveHtmlDashboardRequest,
    SavePdfReportRequest,
    SavePptxReportRequest,
)

router = APIRouter(prefix="/tools", tags=["gpt-tools"])


def _validated(model: type[BaseModel], payload: dict) -> BaseModel:
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"message": "Invalid payload for the selected action.", "errors": exc.errors()},
        ) from exc


def _required_text(payload: dict, key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise HTTPException(status_code=422, detail=f"{key} is required for the selected action.")
    return value


LEAD_ACCESS_REQUIRED_PERMISSIONS = [
    "leads_retrieval",
    "pages_manage_ads",
    "pages_show_list",
    "pages_read_engagement",
]


@router.post(
    "/meta_tracking",
    summary="Meta tracking operations",
    description=(
        "Unified Meta tracking read tool. List Pixels, read received Pixel event names from Pixel stats, or list "
        "Custom Conversions. Use received_pixel_events when the user asks which events Meta actually received."
    ),
)
async def meta_tracking_tool(body: MetaTrackingToolRequest, token: str = Depends(resolve_access_token)):
    payload = body.merged_payload()
    if body.action == "received_pixel_events":
        return await pixels.pixel_event_catalog(_validated(PixelEventCatalogRequest, payload), token)
    if body.action == "diagnose_lead_access":
        return _diagnose_lead_access(payload, token)
    if body.action == "lead_forms":
        page_id = _required_text(payload, "page_id")
        return await leadgen.list_leadgen_forms(
            page_id=page_id,
            fields=payload.get("fields") or "id,name,status,created_time,leads_count,questions,privacy_policy_url",
            limit=payload.get("limit", 100),
            after=payload.get("after"),
            fetch_all=payload.get("fetch_all", False),
            max_pages=payload.get("max_pages", 10),
            token=token,
        )
    if body.action == "form_leads":
        form_id = _required_text(payload, "form_id")
        page_id = _required_text(payload, "page_id")
        page_token = resolve_page_token_for_page_id(token, page_id)
        return meta_call(
            "GET",
            f"{form_id}/leads",
            page_token,
            params={
                "fields": payload.get("fields") or "id,created_time,ad_id,ad_name,adset_id,adset_name,campaign_id,campaign_name,form_id,field_data,platform,is_organic",
                "limit": payload.get("limit", 100),
            },
        )
    account_id = normalize_account_id(_required_text(payload, "account_id"))
    if body.action == "custom_conversions":
        return meta_call(
            "GET",
            f"{account_id}/customconversions",
            token,
            params={"fields": payload.get("fields") or "id,name,custom_event_type,rule,creation_time", "limit": payload.get("limit", 100)},
        )
    return await pixels.list_pixels(
        account_id=account_id,
        fields=payload.get("fields") or "id,name,last_fired_time,creation_time,owner_ad_account,event_stats",
        limit=payload.get("limit", 100),
        after=payload.get("after"),
        fetch_all=payload.get("fetch_all", False),
        max_pages=payload.get("max_pages", 10),
        token=token,
    )


def _diagnose_lead_access(payload: dict, token: str) -> dict:
    page_id = str(payload.get("page_id") or "").strip()
    permissions_payload = {}
    permissions_error = None
    try:
        permissions_payload = meta_call("GET", "me/permissions", token)
    except HTTPException as exc:
        permissions_error = exc.detail
    granted = sorted(
        item.get("permission")
        for item in permissions_payload.get("data", [])
        if item.get("status") == "granted" and item.get("permission")
    )
    missing = [permission for permission in LEAD_ACCESS_REQUIRED_PERMISSIONS if permission not in granted]
    page_token_available = False
    page_token_error = None
    if page_id:
        try:
            resolve_page_token_for_page_id(token, page_id)
            page_token_available = True
        except HTTPException as exc:
            page_token_error = exc.detail
    return {
        "source": "meta_lead_ads_access",
        "page_id": page_id or None,
        "granted_permissions": granted,
        "missing_required_permissions": missing,
        "page_token_available": page_token_available,
        "permissions_error": permissions_error,
        "page_token_error": page_token_error,
        "can_read_lead_forms": not missing and (page_token_available if page_id else True),
        "next_steps": [
            "Add pages_manage_ads to META_OAUTH_SCOPES and reconnect Meta.",
            "In Meta App Review, request advanced access for pages_manage_ads and leads_retrieval for real clients.",
            "Make sure the connected user has Page task access and Leads Access for the Page.",
        ] if missing or page_token_error else [],
    }


@router.post(
    "/ga4",
    summary="GA4 operations",
    description=(
        "Unified GA4 tool. Use action=list_properties or select_property for setup; custom_report for flexible "
        "dimensions, metrics, filters, and sorting; funnel, realtime, or metadata when specifically requested; "
        "and landing_pages, traffic_sources, events, or devices for compact standard reports."
    ),
)
async def ga4_tool(body: GA4ToolRequest, request: Request):
    payload = body.merged_payload()
    if body.action == "list_properties":
        return await ga4.ga4_properties(request, payload.get("tenant_id"))
    if body.action == "select_property":
        return await ga4.ga4_select_property(_validated(GA4PropertySelectionRequest, payload), request)
    if body.action == "custom_report":
        return await ga4.ga4_custom_report(_validated(GA4CustomReportRequest, payload), request)
    if body.action == "funnel":
        return await ga4.ga4_funnel(_validated(GA4FunnelReportRequest, payload), request)
    if body.action == "realtime":
        dimensions = payload.get("dimensions")
        if isinstance(dimensions, list):
            dimensions = ",".join(str(item) for item in dimensions)
        return await ga4.ga4_realtime(
            request,
            payload.get("tenant_id"),
            payload.get("property_id"),
            dimensions,
            payload.get("limit", 100),
        )
    if body.action == "metadata":
        return await ga4.ga4_metadata(request, payload.get("tenant_id"), payload.get("property_id"))
    return await _ga4_standard_report(body.action, payload, request)


async def _ga4_standard_report(action: str, payload: dict, request: Request):
    validated = _validated(GA4DateRangeRequest, payload)
    handler = {
        "landing_pages": ga4.ga4_landing_pages,
        "traffic_sources": ga4.ga4_traffic_sources,
        "events": ga4.ga4_events,
        "devices": ga4.ga4_devices,
    }.get(action)
    if not handler:
        raise HTTPException(status_code=400, detail="Unsupported GA4 tool action.")
    return await handler(
        request,
        validated.tenant_id,
        validated.property_id,
        validated.start_date,
        validated.end_date,
        validated.limit,
    )


@router.post(
    "/website",
    summary="Website intelligence operations",
    description=(
        "Unified website intelligence tool. Use analyze for the full GA4 website assessment, or select a focused "
        "tracking_audit, landing_pages_audit, traffic_quality, device_analysis, or conversion_analysis action."
    ),
)
async def website_tool(body: WebsiteToolRequest, request: Request):
    validated = _validated(WebsiteAnalysisRequest, body.merged_payload())
    handler = {
        "analyze": website_analysis.website_analyze,
        "tracking_audit": website_analysis.website_tracking_audit,
        "landing_pages_audit": website_analysis.website_landing_pages_audit,
        "traffic_quality": website_analysis.website_traffic_quality,
        "device_analysis": website_analysis.website_device_analysis,
        "conversion_analysis": website_analysis.website_conversion_analysis,
    }[body.action]
    return await handler(validated, request)


@router.post(
    "/journey",
    summary="Meta GA4 journey operations",
    description=(
        "Unified customer-journey tool. Use analyze for the full Meta plus GA4 assessment. Use tracking_integrity, "
        "ad_to_site_matching, utm_audit, or decision for a focused answer. Use analyze_from_payload when Meta rows "
        "come from an external connector instead of the tenant Meta connection."
    ),
)
async def journey_tool(body: JourneyToolRequest, request: Request):
    payload = body.merged_payload()
    if body.action == "analyze_from_payload":
        return await journey.journey_analyze_from_payload(_validated(JourneyPayloadAnalysisRequest, payload), request)
    if body.action == "utm_audit":
        return await journey.journey_utm_audit(_validated(MetaTrackingAuditRequest, payload), request)
    validated = _validated(JourneyAnalysisRequest, payload)
    handler = {
        "analyze": journey.journey_analyze,
        "tracking_integrity": journey.journey_tracking_integrity,
        "ad_to_site_matching": journey.journey_ad_to_site_matching,
        "decision": journey.journey_decision,
    }[body.action]
    return await handler(validated, request)


@router.post(
    "/clarity",
    summary="Clarity behavior operations",
    description=(
        "Unified Microsoft Clarity read tool. Use behavior_audit for summarized behavior signals, pages for a compact "
        "URL view, or summary for a compact export summary. Keep row_limit small unless the user needs detail."
    ),
)
async def clarity_tool(body: ClarityToolRequest, request: Request):
    payload = body.merged_payload()
    if body.action == "behavior_audit":
        return await clarity.clarity_behavior_audit(_validated(ClarityBehaviorAuditRequest, payload), request)
    validated = _validated(ClarityRequest, payload)
    if body.action == "pages":
        return await clarity.clarity_pages(validated, request)
    return await clarity.clarity_summary(validated, request)


@router.post(
    "/reports",
    summary="Generate report",
    description=(
        "Unified report generator. Use excel, pdf, pptx, docx, or html_dashboard for a custom report. Use "
        "website_* or journey_* actions to format intelligence payloads without rebuilding report sections manually."
    ),
)
async def report_tool(body: ReportToolRequest):
    handler, model = {
        "excel": (reports.save_excel_report, SaveExcelReportRequest),
        "pdf": (reports.save_pdf_report, SavePdfReportRequest),
        "pptx": (reports.save_pptx_report, SavePptxReportRequest),
        "docx": (reports.save_docx_report, SaveDocxReportRequest),
        "html_dashboard": (reports.save_html_dashboard, SaveHtmlDashboardRequest),
        "website_html": (reports.save_website_html_report, IntelligenceReportRequest),
        "website_excel": (reports.save_website_excel_report, IntelligenceReportRequest),
        "website_pdf": (reports.save_website_pdf_report, IntelligenceReportRequest),
        "website_docx": (reports.save_website_docx_report, IntelligenceReportRequest),
        "journey_html": (reports.save_journey_html_report, IntelligenceReportRequest),
        "journey_excel": (reports.save_journey_excel_report, IntelligenceReportRequest),
        "journey_pdf": (reports.save_journey_pdf_report, IntelligenceReportRequest),
        "journey_docx": (reports.save_journey_docx_report, IntelligenceReportRequest),
    }[body.action]
    return await handler(_validated(model, body.merged_payload()))
