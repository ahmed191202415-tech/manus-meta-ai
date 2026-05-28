from fastapi import APIRouter, Request

from app.analytics.ad_site_matching import build_ad_site_matching
from app.analytics.ga4_preprocessing import normalize_ga4_report
from app.analytics.journey_metrics import build_journey_metrics
from app.analytics.journey_signals import build_journey_signals
from app.analytics.preprocessing import fetch_insights_df
from app.analytics.tracking_quality import build_tracking_quality
from app.analytics.website_metrics import summarize_website_metrics
from app.analytics.website_signals import build_website_signals
from app.core.auth import resolve_access_token
from app.core.ga4_client import run_ga4_report
from app.schemas.ga4_requests import JourneyAnalysisRequest

router = APIRouter(prefix="/journey", tags=["journey"])


@router.post("/analyze")
async def journey_analyze(body: JourneyAnalysisRequest, request: Request):
    token = await resolve_access_token(request)
    meta_df = fetch_insights_df(
        body.meta_account_id,
        token,
        body.level,
        None,
        body.date_preset,
        None,
        None,
        None,
        None,
    )
    meta_rows = meta_df.head(body.limit).to_dict(orient="records") if not meta_df.empty else []
    tenant_id = body.tenant_id or request.session.get("tenant_id") or ""
    ga4_reports = _ga4_journey_reports(tenant_id, body.ga4_property_id, body.start_date, body.end_date, body.limit)
    website_summary = summarize_website_metrics(ga4_reports["traffic"], ga4_reports["landing"], ga4_reports["events"], ga4_reports["devices"])
    tracking_quality = build_tracking_quality(True, bool(body.ga4_property_id), ga4_reports["traffic"], ga4_reports["landing"], ga4_reports["events"])
    website_signals = build_website_signals(website_summary, tracking_quality, ga4_reports["landing"], ga4_reports["traffic"], ga4_reports["devices"])
    matching = build_ad_site_matching(meta_rows, ga4_reports["traffic"])
    metrics = build_journey_metrics(meta_rows, website_summary)
    signals = build_journey_signals(metrics, matching, website_signals)
    return {
        "mode": "meta_ga4_journey",
        "tenant_id": tenant_id,
        "meta_account_id": body.meta_account_id,
        "ga4_property_id": body.ga4_property_id,
        "date_range": {"start_date": body.start_date, "end_date": body.end_date, "date_preset": body.date_preset},
        "matching": matching,
        "summary_metrics": metrics,
        "tracking_quality": tracking_quality,
        "website_signals": website_signals,
        "signals": signals,
        "decision_hints": [item["decision_hint"] for item in signals],
        "missing_data": matching.get("limits", []) + tracking_quality.get("missing_events", []),
    }


@router.post("/tracking_integrity")
async def journey_tracking_integrity(body: JourneyAnalysisRequest, request: Request):
    result = await journey_analyze(body, request)
    return {
        "matching": result["matching"],
        "tracking_quality": result["tracking_quality"],
        "summary_metrics": result["summary_metrics"],
        "signals": [item for item in result["signals"] if "tracking" in item["signal"] or "gap" in item["signal"]],
    }


@router.post("/ad_to_site_matching")
async def journey_ad_to_site_matching(body: JourneyAnalysisRequest, request: Request):
    result = await journey_analyze(body, request)
    return result["matching"]


@router.post("/decision")
async def journey_decision(body: JourneyAnalysisRequest, request: Request):
    result = await journey_analyze(body, request)
    confidence = "medium" if result["matching"]["matching_confidence"] in {"medium", "high"} and result["tracking_quality"]["level"] != "weak" else "low"
    return {
        "confidence": confidence,
        "decision_hints": result["decision_hints"],
        "ranked_issues": result["signals"],
        "missing_data": result["missing_data"],
    }


def _ga4_journey_reports(tenant_id: str, property_id: str | None, start_date: str, end_date: str, limit: int) -> dict:
    traffic = normalize_ga4_report(run_ga4_report(
        tenant_id, property_id,
        ["sessionSourceMedium", "sessionCampaignName"],
        ["sessions", "activeUsers", "engagedSessions", "engagementRate", "conversions", "totalRevenue"],
        start_date, end_date, limit,
    ))
    landing = normalize_ga4_report(run_ga4_report(
        tenant_id, property_id,
        ["landingPagePlusQueryString", "sessionSourceMedium", "deviceCategory"],
        ["sessions", "activeUsers", "engagedSessions", "engagementRate", "conversions", "totalRevenue"],
        start_date, end_date, limit,
    ))
    events = normalize_ga4_report(run_ga4_report(
        tenant_id, property_id,
        ["eventName"],
        ["eventCount", "activeUsers"],
        start_date, end_date, limit,
    ))
    devices = normalize_ga4_report(run_ga4_report(
        tenant_id, property_id,
        ["deviceCategory"],
        ["sessions", "engagedSessions", "engagementRate", "conversions", "totalRevenue"],
        start_date, end_date, limit,
    ))
    return {"traffic": traffic, "landing": landing, "events": events, "devices": devices}
