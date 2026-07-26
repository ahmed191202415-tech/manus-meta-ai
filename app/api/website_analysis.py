from fastapi import APIRouter, Query, Request

from app.analytics.ga4_preprocessing import normalize_ga4_report
from app.analytics.tracking_quality import build_tracking_quality
from app.analytics.website_metrics import summarize_website_metrics, top_entities
from app.analytics.website_signals import build_website_signals
from app.core.ga4_client import resolve_ga4_property_id, run_ga4_report
from app.core.tenant_resolver import resolve_tenant_id_for_google
from app.schemas.ga4_requests import WebsiteAnalysisRequest

router = APIRouter(prefix="/website", tags=["website-analysis"])


def _resolve_tenant_id(request: Request, tenant_id: str | None = None) -> str:
    return resolve_tenant_id_for_google(request, tenant_id)


def _fetch_standard_reports(tenant_id: str, property_id: str | None, start_date: str, end_date: str, limit: int) -> dict:
    resolved_property_id = resolve_ga4_property_id(tenant_id, property_id)
    errors = []
    traffic = _safe_ga4_rows(
        errors,
        "traffic_sources",
        tenant_id,
        resolved_property_id,
        ["sessionSourceMedium", "sessionCampaignName"],
        ["sessions", "activeUsers", "engagedSessions", "engagementRate", "conversions", "totalRevenue"],
        start_date,
        end_date,
        limit,
    )
    landing = _safe_ga4_rows(
        errors,
        "landing_pages",
        tenant_id,
        resolved_property_id,
        ["landingPagePlusQueryString", "sessionSourceMedium", "deviceCategory"],
        ["sessions", "activeUsers", "engagedSessions", "engagementRate", "averageSessionDuration", "conversions", "totalRevenue"],
        start_date,
        end_date,
        limit,
    )
    events = _safe_ga4_rows(
        errors,
        "events",
        tenant_id,
        resolved_property_id,
        ["eventName"],
        ["eventCount", "activeUsers"],
        start_date,
        end_date,
        limit,
    )
    devices = _safe_ga4_rows(
        errors,
        "devices",
        tenant_id,
        resolved_property_id,
        ["deviceCategory"],
        ["sessions", "engagedSessions", "engagementRate", "conversions", "totalRevenue"],
        start_date,
        end_date,
        limit,
    )
    return {
        "property_id": resolved_property_id,
        "traffic_sources": traffic,
        "landing_pages": landing,
        "events": events,
        "devices": devices,
        "_errors": errors,
    }


def _safe_ga4_rows(
    errors: list[dict],
    report_name: str,
    tenant_id: str,
    property_id: str,
    dimensions: list[str],
    metrics: list[str],
    start_date: str,
    end_date: str,
    limit: int,
) -> list[dict]:
    try:
        return normalize_ga4_report(run_ga4_report(tenant_id, property_id, dimensions, metrics, start_date, end_date, limit))
    except Exception as exc:
        fallback_metrics = [metric for metric in metrics if metric not in {"conversions", "totalRevenue"}]
        errors.append({"source": f"ga4_{report_name}", "message": _safe_error(exc), "fallback_metrics": fallback_metrics})
        if not fallback_metrics:
            return []
        try:
            return normalize_ga4_report(run_ga4_report(tenant_id, property_id, dimensions, fallback_metrics, start_date, end_date, limit))
        except Exception as fallback_exc:
            errors.append({"source": f"ga4_{report_name}_fallback", "message": _safe_error(fallback_exc)})
            return []


def _safe_error(exc: Exception) -> str:
    detail = getattr(exc, "detail", None)
    if detail is not None:
        return str(detail)
    return str(exc)


@router.post("/analyze")
async def website_analyze(body: WebsiteAnalysisRequest, request: Request):
    tenant_id = _resolve_tenant_id(request, body.tenant_id)
    reports = _fetch_standard_reports(tenant_id, body.property_id, body.start_date, body.end_date, body.limit)
    summary = summarize_website_metrics(
        reports["traffic_sources"],
        reports["landing_pages"],
        reports["events"],
        reports["devices"],
    )
    quality = build_tracking_quality(
        connected=True,
        property_selected=bool(reports["property_id"]),
        traffic_rows=reports["traffic_sources"],
        landing_page_rows=reports["landing_pages"],
        event_rows=reports["events"],
    )
    signals = build_website_signals(summary, quality, reports["landing_pages"], reports["traffic_sources"], reports["devices"])
    return {
        "mode": "ga4_only",
        "tenant_id": tenant_id,
        "property_id": reports["property_id"],
        "date_range": {"start_date": body.start_date, "end_date": body.end_date},
        "summary_metrics": summary,
        "tracking_quality": quality,
        "signals": signals,
        "top_entities": {
            "landing_pages": top_entities(reports["landing_pages"]),
            "traffic_sources": top_entities(reports["traffic_sources"]),
            "devices": top_entities(reports["devices"]),
        },
        "missing_data": summary.get("missing_metrics", []),
        "partial_data": bool(reports.get("_errors")),
        "data_errors": reports.get("_errors", []),
        "recommended_focus": _recommended_focus(signals),
    }


@router.post("/tracking_audit")
async def website_tracking_audit(body: WebsiteAnalysisRequest, request: Request):
    tenant_id = _resolve_tenant_id(request, body.tenant_id)
    reports = _fetch_standard_reports(tenant_id, body.property_id, body.start_date, body.end_date, body.limit)
    return build_tracking_quality(True, bool(reports["property_id"]), reports["traffic_sources"], reports["landing_pages"], reports["events"])


@router.post("/landing_pages_audit")
async def website_landing_pages_audit(body: WebsiteAnalysisRequest, request: Request):
    tenant_id = _resolve_tenant_id(request, body.tenant_id)
    reports = _fetch_standard_reports(tenant_id, body.property_id, body.start_date, body.end_date, body.limit)
    summary = summarize_website_metrics(reports["traffic_sources"], reports["landing_pages"], reports["events"], reports["devices"])
    quality = build_tracking_quality(True, bool(reports["property_id"]), reports["traffic_sources"], reports["landing_pages"], reports["events"])
    signals = [item for item in build_website_signals(summary, quality, reports["landing_pages"], reports["traffic_sources"], reports["devices"]) if "landing_page" in item["signal"] or item["affected_entities"]]
    return {"landing_pages": top_entities(reports["landing_pages"]), "signals": signals}


@router.post("/traffic_quality")
async def website_traffic_quality(body: WebsiteAnalysisRequest, request: Request):
    tenant_id = _resolve_tenant_id(request, body.tenant_id)
    reports = _fetch_standard_reports(tenant_id, body.property_id, body.start_date, body.end_date, body.limit)
    return {"traffic_sources": top_entities(reports["traffic_sources"]), "summary": summarize_website_metrics(reports["traffic_sources"], reports["landing_pages"], reports["events"], reports["devices"])}


@router.post("/device_analysis")
async def website_device_analysis(body: WebsiteAnalysisRequest, request: Request):
    tenant_id = _resolve_tenant_id(request, body.tenant_id)
    reports = _fetch_standard_reports(tenant_id, body.property_id, body.start_date, body.end_date, body.limit)
    return {"devices": top_entities(reports["devices"]), "summary": summarize_website_metrics(reports["traffic_sources"], reports["landing_pages"], reports["events"], reports["devices"])}


@router.post("/conversion_analysis")
async def website_conversion_analysis(body: WebsiteAnalysisRequest, request: Request):
    tenant_id = _resolve_tenant_id(request, body.tenant_id)
    reports = _fetch_standard_reports(tenant_id, body.property_id, body.start_date, body.end_date, body.limit)
    summary = summarize_website_metrics(reports["traffic_sources"], reports["landing_pages"], reports["events"], reports["devices"])
    quality = build_tracking_quality(True, bool(reports["property_id"]), reports["traffic_sources"], reports["landing_pages"], reports["events"])
    return {"summary": summary, "tracking_quality": quality, "events": top_entities(reports["events"], "eventCount")}


@router.get("/quick_analyze")
async def website_quick_analyze(
    request: Request,
    tenant_id: str = Query(...),
    property_id: str | None = None,
    start_date: str = "30daysAgo",
    end_date: str = "today",
):
    return await website_analyze(WebsiteAnalysisRequest(tenant_id=tenant_id, property_id=property_id, start_date=start_date, end_date=end_date), request)


def _recommended_focus(signals: list[dict]) -> list[str]:
    focus = []
    for signal in signals:
        if "mobile" in signal["signal"]:
            focus.append("mobile_experience")
        if "landing_page" in signal["signal"] or signal["affected_entities"]:
            focus.append("landing_pages")
        if "tracking" in signal["signal"]:
            focus.append("tracking")
    return list(dict.fromkeys(focus))[:5]
