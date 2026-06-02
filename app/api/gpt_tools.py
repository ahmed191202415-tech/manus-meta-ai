from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ValidationError

from app.api import clarity, ga4, journey, reports, website_analysis
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
    ReportToolRequest,
    WebsiteToolRequest,
)
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
    payload = body.payload
    if body.action == "list_properties":
        return await ga4.ga4_properties(request, payload.get("tenant_id"))
    if body.action == "select_property":
        return await ga4.ga4_select_property(_validated(GA4PropertySelectionRequest, payload), request)
    if body.action == "custom_report":
        return await ga4.ga4_custom_report(_validated(GA4CustomReportRequest, payload), request)
    if body.action == "funnel":
        return await ga4.ga4_funnel(_validated(GA4FunnelReportRequest, payload), request)
    if body.action == "realtime":
        return await ga4.ga4_realtime(
            request,
            payload.get("tenant_id"),
            payload.get("property_id"),
            payload.get("dimensions"),
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
    validated = _validated(WebsiteAnalysisRequest, body.payload)
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
    if body.action == "analyze_from_payload":
        return await journey.journey_analyze_from_payload(_validated(JourneyPayloadAnalysisRequest, body.payload), request)
    if body.action == "utm_audit":
        return await journey.journey_utm_audit(_validated(MetaTrackingAuditRequest, body.payload), request)
    validated = _validated(JourneyAnalysisRequest, body.payload)
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
    if body.action == "behavior_audit":
        return await clarity.clarity_behavior_audit(_validated(ClarityBehaviorAuditRequest, body.payload), request)
    validated = _validated(ClarityRequest, body.payload)
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
    return await handler(_validated(model, body.payload))
