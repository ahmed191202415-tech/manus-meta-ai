from fastapi import APIRouter, Request

from app.analytics.ad_site_matching import build_ad_site_matching
from app.analytics.ga4_preprocessing import normalize_ga4_report
from app.analytics.journey_metrics import build_journey_metrics
from app.analytics.journey_signals import build_journey_signals
from app.analytics.preprocessing import fetch_insights_df
from app.analytics.tracking_quality import build_tracking_quality
from app.analytics.tracking_links import audit_meta_tracking_links
from app.analytics.website_metrics import summarize_website_metrics
from app.analytics.website_signals import build_website_signals
from app.core.auth import resolve_access_token
from app.core.ga4_client import run_ga4_report
from app.core.meta_client import meta_call, normalize_account_id
from app.core.pagination import meta_get_all_pages
from app.core.tenant_resolver import resolve_tenant_id_for_google
from app.schemas.ga4_requests import JourneyAnalysisRequest, MetaTrackingAuditRequest

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
    tenant_id = resolve_tenant_id_for_google(request, body.tenant_id)
    ga4_reports = _ga4_journey_reports(tenant_id, body.ga4_property_id, body.start_date, body.end_date, body.limit)
    website_summary = summarize_website_metrics(ga4_reports["traffic"], ga4_reports["landing"], ga4_reports["events"], ga4_reports["devices"])
    tracking_quality = build_tracking_quality(True, bool(body.ga4_property_id), ga4_reports["traffic"], ga4_reports["landing"], ga4_reports["events"])
    website_signals = build_website_signals(website_summary, tracking_quality, ga4_reports["landing"], ga4_reports["traffic"], ga4_reports["devices"])
    creative_rows = _fetch_meta_ads_with_creatives(body.meta_account_id, token, body.limit)
    link_audit = audit_meta_tracking_links(creative_rows, ga4_reports["landing"])
    matching = build_ad_site_matching(meta_rows, ga4_reports["traffic"], link_audit)
    metrics = build_journey_metrics(meta_rows, website_summary)
    signals = build_journey_signals(metrics, matching, website_signals)
    return {
        "mode": "meta_ga4_journey",
        "tenant_id": tenant_id,
        "meta_account_id": body.meta_account_id,
        "ga4_property_id": body.ga4_property_id,
        "date_range": {"start_date": body.start_date, "end_date": body.end_date, "date_preset": body.date_preset},
        "matching": matching,
        "tracking_link_audit": link_audit,
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


@router.post("/utm_audit")
async def journey_utm_audit(body: MetaTrackingAuditRequest, request: Request):
    token = await resolve_access_token(request)
    tenant_id = resolve_tenant_id_for_google(request, body.tenant_id)
    landing_rows = []
    try:
        landing_rows = normalize_ga4_report(run_ga4_report(
            tenant_id,
            body.ga4_property_id,
            ["landingPagePlusQueryString", "sessionSourceMedium"],
            ["sessions"],
            body.start_date,
            body.end_date,
            body.limit,
        ))
    except Exception:
        landing_rows = []
    creative_rows = _fetch_meta_ads_with_creatives(body.meta_account_id, token, body.limit)
    return audit_meta_tracking_links(creative_rows, landing_rows)


@router.post("/decision")
async def journey_decision(body: JourneyAnalysisRequest, request: Request):
    result = await journey_analyze(body, request)
    confidence = "medium" if result["matching"]["matching_confidence"] in {"medium", "high"} and result["tracking_quality"]["level"] != "weak" else "low"
    decision = _journey_decision_label(result, confidence)
    return {
        "confidence": confidence,
        "decision": decision["decision"],
        "primary_reason": decision["primary_reason"],
        "next_action": decision["next_action"],
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


def _fetch_meta_ads_with_creatives(account_id: str, token: str, limit: int) -> list[dict]:
    account_id = normalize_account_id(account_id)
    fields = (
        "id,name,campaign_id,campaign{name},adset_id,adset{name},creative{"
        "id,name,url_tags,object_story_spec,asset_feed_spec,effective_object_story_id,thumbnail_url"
        "}"
    )
    try:
        payload = meta_get_all_pages(
            f"{account_id}/ads",
            token,
            params={"fields": fields, "limit": min(max(int(limit or 100), 1), 100)},
            max_pages=3,
        )
        rows = payload.get("data", [])
    except Exception:
        rows = meta_call("GET", f"{account_id}/ads", token, params={"fields": fields, "limit": min(max(int(limit or 100), 1), 100)}).get("data", [])
    normalized = []
    for row in rows[:limit]:
        campaign = row.get("campaign") or {}
        adset = row.get("adset") or {}
        normalized.append({
            **row,
            "campaign_name": campaign.get("name") or row.get("campaign_name"),
            "adset_name": adset.get("name") or row.get("adset_name"),
        })
    return normalized


def _journey_decision_label(result: dict, confidence: str) -> dict:
    signals = result.get("signals") or []
    names = {item.get("signal") for item in signals}
    quality = result.get("tracking_quality") or {}
    matching = result.get("matching") or {}

    if confidence == "low" or quality.get("level") == "weak" or "ad_to_page_match_low_confidence" in names:
        return {
            "decision": "Fix Tracking",
            "primary_reason": "Matching or tracking quality is not strong enough for a performance decision.",
            "next_action": "Fix UTMs, add ad_id/campaign_id, and verify GA4 conversion events before scaling or stopping ads.",
        }
    if "click_session_loss" in names:
        return {
            "decision": "Hold",
            "primary_reason": "Meta clicks are not turning into GA4 sessions at a healthy rate.",
            "next_action": "Check final URL, redirects, page load, and session attribution before changing budget.",
        }
    if "ad_good_site_weak" in names or "mobile_paid_social_issue" in names:
        return {
            "decision": "Fix Landing Page",
            "primary_reason": "Traffic is arriving but site engagement or mobile behavior is weak.",
            "next_action": "Improve landing page speed, message match, mobile UX, CTA, and trust elements.",
        }
    if "engaged_no_conversion" in names:
        return {
            "decision": "Fix CTA",
            "primary_reason": "Users engage with the site but do not convert.",
            "next_action": "Review form friction, offer clarity, pricing, CTA placement, and conversion event setup.",
        }
    if matching.get("matching_confidence") == "high":
        return {
            "decision": "Scale Carefully",
            "primary_reason": "Meta to GA4 matching is strong and no blocking journey signal was found.",
            "next_action": "Scale gradually while monitoring click-to-session and conversion rates.",
        }
    return {
        "decision": "Hold",
        "primary_reason": "No strong positive or negative decision signal was found.",
        "next_action": "Collect more data or improve tracking confidence before making a larger budget decision.",
    }
