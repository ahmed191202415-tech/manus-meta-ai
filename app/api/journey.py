from fastapi import APIRouter, Request

from app.analytics.ad_site_matching import build_ad_site_matching
from app.analytics.clarity_ad_matching import build_clarity_ad_behavior
from app.analytics.clarity_metrics import normalize_clarity_export, summarize_clarity_metrics
from app.analytics.clarity_signals import build_clarity_signals
from app.analytics.ga4_preprocessing import normalize_ga4_report
from app.analytics.goal_context import build_goal_context
from app.analytics.journey_metrics import build_journey_metrics
from app.analytics.journey_signals import build_journey_signals
from app.analytics.preprocessing import fetch_insights_df
from app.analytics.tracking_quality import build_tracking_quality
from app.analytics.tracking_links import audit_meta_tracking_links
from app.analytics.website_metrics import summarize_website_metrics
from app.analytics.website_signals import build_website_signals
from app.core.auth import resolve_access_token
from app.core.clarity_client import run_clarity_live_insights_with_fallbacks
from app.core.ga4_client import run_ga4_report
from app.core.meta_client import meta_call, normalize_account_id
from app.core.pagination import meta_get_all_pages
from app.core.tenant_resolver import resolve_tenant_id_for_google
from app.schemas.ga4_requests import JourneyAnalysisRequest, JourneyPayloadAnalysisRequest, MetaTrackingAuditRequest
from app.api.insights import _build_insights_filters

router = APIRouter(prefix="/journey", tags=["journey"])


@router.post("/analyze")
async def journey_analyze(body: JourneyAnalysisRequest, request: Request):
    token = await resolve_access_token(request)
    data_errors = []
    inferred_scope = _infer_journey_scope(body, token)
    effective_body = body.model_copy(update=inferred_scope.get("filters", {}))
    try:
        filters = _journey_meta_filters(effective_body)
        meta_df = fetch_insights_df(
            effective_body.meta_account_id,
            token,
            _resolve_meta_level(effective_body),
            None,
            effective_body.date_preset,
            None,
            None,
            filters,
            None,
        )
        meta_rows = meta_df.head(body.limit).to_dict(orient="records") if not meta_df.empty else []
    except Exception as exc:
        meta_rows = []
        data_errors.append({"source": "meta_insights", "message": _safe_error(exc)})

    tenant_id = resolve_tenant_id_for_google(request, effective_body.tenant_id)
    ga4_reports = _ga4_journey_reports(tenant_id, effective_body.ga4_property_id, effective_body.start_date, effective_body.end_date, effective_body.limit)
    data_errors.extend(ga4_reports.get("_errors", []))
    website_summary = summarize_website_metrics(ga4_reports["traffic"], ga4_reports["landing"], ga4_reports["events"], ga4_reports["devices"])
    tracking_quality = build_tracking_quality(True, bool(body.ga4_property_id), ga4_reports["traffic"], ga4_reports["landing"], ga4_reports["events"])
    website_signals = build_website_signals(website_summary, tracking_quality, ga4_reports["landing"], ga4_reports["traffic"], ga4_reports["devices"])
    try:
        creative_rows = _filter_meta_creative_rows(
            _fetch_meta_ads_with_creatives(effective_body.meta_account_id, token, effective_body.limit),
            effective_body,
        )
        link_audit = audit_meta_tracking_links(creative_rows, ga4_reports["landing"])
    except Exception as exc:
        link_audit = {
            "tracking_link_score": 0,
            "total_links": 0,
            "utm_complete_links": 0,
            "strong_id_links": 0,
            "matched_landing_pages": [],
            "missing_key_counts": {},
            "links": [],
            "recommendations": ["Could not inspect Meta creative URLs. Check ads_read permissions and creative fields."],
        }
        data_errors.append({"source": "meta_creatives", "message": _safe_error(exc)})

    matching = build_ad_site_matching(meta_rows, ga4_reports["traffic"], link_audit)
    goal_context = build_goal_context(meta_rows)
    matched_entities = _build_matched_entities(meta_rows, creative_rows if "creative_rows" in locals() else [], ga4_reports["traffic"])
    metrics = build_journey_metrics(meta_rows, website_summary)
    signals = build_journey_signals(metrics, matching, website_signals)
    clarity = _optional_clarity_behavior(effective_body, tenant_id, matched_entities, link_audit, data_errors)
    return {
        "mode": "meta_ga4_journey",
        "tenant_id": tenant_id,
        "meta_account_id": effective_body.meta_account_id,
        "ga4_property_id": effective_body.ga4_property_id,
        "date_range": {"start_date": effective_body.start_date, "end_date": effective_body.end_date, "date_preset": effective_body.date_preset},
        "meta_filter": {
            "campaign_id": effective_body.campaign_id,
            "campaign_name": effective_body.campaign_name,
            "adset_id": effective_body.adset_id,
            "ad_id": effective_body.ad_id,
            "level": _resolve_meta_level(effective_body),
            "auto_selected": inferred_scope.get("auto_selected", False),
            "auto_selection_reason": inferred_scope.get("reason"),
        },
        "ga4_filter_limits": _ga4_filter_limits(effective_body),
        "goal_context": goal_context,
        "matching": matching,
        "matched_entities": matched_entities,
        "tracking_link_audit": link_audit,
        "summary_metrics": metrics,
        "tracking_quality": tracking_quality,
        "website_signals": website_signals,
        "clarity": clarity,
        "signals": signals,
        "decision_hints": [item["decision_hint"] for item in signals],
        "missing_data": matching.get("limits", []) + tracking_quality.get("missing_events", []),
        "partial_data": bool(data_errors),
        "data_errors": data_errors,
    }


@router.post("/analyze_from_payload")
async def journey_analyze_from_payload(body: JourneyPayloadAnalysisRequest, request: Request):
    data_errors = []
    tenant_id = resolve_tenant_id_for_google(request, body.tenant_id)
    meta_rows = _filter_meta_payload_rows(_normalize_meta_payload_rows(body.meta_rows), body)[:body.limit]
    creative_source_rows = body.creative_rows or body.meta_rows
    creative_rows = _filter_meta_payload_rows(_normalize_meta_payload_rows(creative_source_rows), body)[:body.limit]
    link_rows = _normalize_meta_payload_rows(body.link_rows)[:body.limit]

    ga4_reports = _ga4_journey_reports(tenant_id, body.ga4_property_id, body.start_date, body.end_date, body.limit)
    data_errors.extend(ga4_reports.get("_errors", []))
    website_summary = summarize_website_metrics(ga4_reports["traffic"], ga4_reports["landing"], ga4_reports["events"], ga4_reports["devices"])
    tracking_quality = build_tracking_quality(True, bool(body.ga4_property_id), ga4_reports["traffic"], ga4_reports["landing"], ga4_reports["events"])
    website_signals = build_website_signals(website_summary, tracking_quality, ga4_reports["landing"], ga4_reports["traffic"], ga4_reports["devices"])

    if creative_rows:
        link_audit = audit_meta_tracking_links(creative_rows, ga4_reports["landing"])
    elif link_rows:
        link_audit = _audit_payload_links(link_rows, ga4_reports["landing"])
    else:
        link_audit = {
            "tracking_link_score": 0,
            "total_links": 0,
            "utm_complete_links": 0,
            "strong_id_links": 0,
            "matched_landing_pages": [],
            "missing_key_counts": {},
            "links": [],
            "recommendations": ["Send creative_rows or link_rows to audit Meta ad URLs without Meta OAuth."],
        }

    matching = build_ad_site_matching(meta_rows, ga4_reports["traffic"], link_audit)
    goal_context = build_goal_context(meta_rows)
    matched_entities = _build_matched_entities(meta_rows, creative_rows, ga4_reports["traffic"])
    metrics = build_journey_metrics(meta_rows, website_summary)
    signals = build_journey_signals(metrics, matching, website_signals)
    clarity = _optional_clarity_behavior(body, tenant_id, matched_entities, link_audit, data_errors)
    return {
        "mode": "meta_ga4_journey",
        "meta_source": "payload",
        "requires_meta_oauth": False,
        "tenant_id": tenant_id,
        "meta_account_id": body.meta_account_id,
        "ga4_property_id": body.ga4_property_id,
        "date_range": {"start_date": body.start_date, "end_date": body.end_date, "date_preset": body.date_preset},
        "meta_filter": {
            "campaign_id": body.campaign_id,
            "campaign_name": body.campaign_name,
            "adset_id": body.adset_id,
            "ad_id": body.ad_id,
            "auto_selected": False,
            "source": "provided_payload",
        },
        "ga4_filter_limits": _ga4_filter_limits(body),
        "goal_context": goal_context,
        "matching": matching,
        "matched_entities": matched_entities,
        "tracking_link_audit": link_audit,
        "summary_metrics": metrics,
        "tracking_quality": tracking_quality,
        "website_signals": website_signals,
        "clarity": clarity,
        "signals": signals,
        "decision_hints": [item["decision_hint"] for item in signals],
        "missing_data": matching.get("limits", []) + tracking_quality.get("missing_events", []),
        "partial_data": bool(data_errors),
        "data_errors": data_errors,
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
        "goal_context": result.get("goal_context"),
        "decision": decision["decision"],
        "primary_reason": decision["primary_reason"],
        "next_action": decision["next_action"],
        "decision_hints": result["decision_hints"],
        "ranked_issues": result["signals"],
        "missing_data": result["missing_data"],
    }


def _ga4_journey_reports(tenant_id: str, property_id: str | None, start_date: str, end_date: str, limit: int) -> dict:
    errors = []
    traffic = _safe_ga4_rows(
        errors, "traffic", tenant_id, property_id,
        ["sessionSourceMedium", "sessionCampaignName", "sessionManualAdContent"],
        ["sessions", "activeUsers", "engagedSessions", "engagementRate", "conversions", "totalRevenue"],
        start_date, end_date, limit,
    )
    landing = _safe_ga4_rows(
        errors, "landing", tenant_id, property_id,
        ["landingPagePlusQueryString", "sessionSourceMedium", "deviceCategory"],
        ["sessions", "activeUsers", "engagedSessions", "engagementRate", "conversions", "totalRevenue"],
        start_date, end_date, limit,
    )
    events = _safe_ga4_rows(
        errors, "events", tenant_id, property_id,
        ["eventName"],
        ["eventCount", "activeUsers"],
        start_date, end_date, limit,
    )
    devices = _safe_ga4_rows(
        errors, "devices", tenant_id, property_id,
        ["deviceCategory"],
        ["sessions", "engagedSessions", "engagementRate", "conversions", "totalRevenue"],
        start_date, end_date, limit,
    )
    return {"traffic": traffic, "landing": landing, "events": events, "devices": devices, "_errors": errors}


def _safe_ga4_rows(
    errors: list[dict],
    report_name: str,
    tenant_id: str,
    property_id: str | None,
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
        errors.append({"source": f"ga4_{report_name}", "message": _safe_error(exc), "fallback": fallback_metrics})
        if not fallback_metrics:
            return []
        try:
            return normalize_ga4_report(run_ga4_report(tenant_id, property_id, dimensions, fallback_metrics, start_date, end_date, limit))
        except Exception as fallback_exc:
            errors.append({"source": f"ga4_{report_name}_fallback", "message": _safe_error(fallback_exc)})
            return []


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
        try:
            rows = meta_call("GET", f"{account_id}/ads", token, params={"fields": fields, "limit": min(max(int(limit or 100), 1), 100)}).get("data", [])
        except Exception:
            return []
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


def _journey_meta_filters(body: JourneyAnalysisRequest) -> str | None:
    filters = _build_insights_filters(None, body.campaign_id, body.campaign_name, body.adset_id, body.ad_id)
    return None if not filters else __import__("json").dumps(filters, ensure_ascii=False)


def _resolve_meta_level(body: JourneyAnalysisRequest) -> str:
    if body.ad_id:
        return "ad"
    if body.adset_id:
        return "adset"
    return body.level


def _filter_meta_creative_rows(rows: list[dict], body: JourneyAnalysisRequest) -> list[dict]:
    result = []
    for row in rows:
        if body.campaign_id and str(row.get("campaign_id") or "").strip() != str(body.campaign_id).strip():
            continue
        if body.campaign_name and str(body.campaign_name).lower() not in str(row.get("campaign_name") or "").lower():
            continue
        if body.adset_id and str(row.get("adset_id") or "").strip() != str(body.adset_id).strip():
            continue
        if body.ad_id and str(row.get("id") or row.get("ad_id") or "").strip() != str(body.ad_id).strip():
            continue
        result.append(row)
    return result


def _normalize_meta_payload_rows(rows: list[dict]) -> list[dict]:
    normalized = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        campaign = item.get("campaign") if isinstance(item.get("campaign"), dict) else {}
        adset = item.get("adset") if isinstance(item.get("adset"), dict) else {}
        ad = item.get("ad") if isinstance(item.get("ad"), dict) else {}
        creative = item.get("creative") if isinstance(item.get("creative"), dict) else {}
        if not item.get("campaign_id"):
            item["campaign_id"] = campaign.get("id") or item.get("campaignId")
        if not item.get("campaign_name"):
            item["campaign_name"] = campaign.get("name") or item.get("campaignName")
        if not item.get("adset_id"):
            item["adset_id"] = adset.get("id") or item.get("adsetId") or item.get("ad_set_id")
        if not item.get("adset_name"):
            item["adset_name"] = adset.get("name") or item.get("adsetName") or item.get("ad_set_name")
        if not item.get("ad_id"):
            item["ad_id"] = ad.get("id") or item.get("adId") or item.get("id")
        if not item.get("ad_name"):
            item["ad_name"] = ad.get("name") or item.get("adName") or item.get("name")
        if creative and not item.get("creative"):
            item["creative"] = creative
        normalized.append(item)
    return normalized


def _filter_meta_payload_rows(rows: list[dict], body: JourneyPayloadAnalysisRequest) -> list[dict]:
    result = []
    for row in rows:
        if body.campaign_id and str(row.get("campaign_id") or "").strip() != str(body.campaign_id).strip():
            continue
        if body.campaign_name and str(body.campaign_name).lower() not in str(row.get("campaign_name") or "").lower():
            continue
        if body.adset_id and str(row.get("adset_id") or "").strip() != str(body.adset_id).strip():
            continue
        if body.ad_id and str(row.get("ad_id") or row.get("id") or "").strip() != str(body.ad_id).strip():
            continue
        result.append(row)
    return result


def _audit_payload_links(link_rows: list[dict], landing_rows: list[dict]) -> dict:
    creative_like_rows = []
    for index, row in enumerate(link_rows):
        url = row.get("url") or row.get("link_url") or row.get("website_url") or row.get("final_url")
        creative_like_rows.append({
            "id": row.get("ad_id") or row.get("id") or f"payload-link-{index + 1}",
            "name": row.get("ad_name") or row.get("name"),
            "campaign_id": row.get("campaign_id"),
            "campaign_name": row.get("campaign_name"),
            "adset_id": row.get("adset_id"),
            "adset_name": row.get("adset_name"),
            "creative": {
                "url_tags": row.get("url_tags"),
                "object_story_spec": {"link_data": {"link": url}} if url else {},
            },
        })
    return audit_meta_tracking_links(creative_like_rows, landing_rows)


def _infer_journey_scope(body: JourneyAnalysisRequest, token: str) -> dict:
    if body.campaign_id or body.campaign_name or body.adset_id or body.ad_id or not body.auto_select_latest_campaign:
        return {"filters": {}, "auto_selected": False, "reason": None}
    campaign = _latest_meta_campaign(body.meta_account_id, token)
    if not campaign:
        return {"filters": {}, "auto_selected": False, "reason": "No campaign could be auto-selected."}
    return {
        "filters": {
            "campaign_id": campaign.get("id"),
            "campaign_name": campaign.get("name"),
        },
        "auto_selected": True,
        "reason": "No campaign/ad/adset filter was provided, so the most recently updated or created campaign was selected.",
        "campaign": campaign,
    }


def _latest_meta_campaign(account_id: str, token: str) -> dict | None:
    account_id = normalize_account_id(account_id)
    fields = "id,name,status,effective_status,created_time,updated_time,start_time"
    try:
        payload = meta_get_all_pages(
            f"{account_id}/campaigns",
            token,
            params={"fields": fields, "limit": 100},
            max_pages=2,
        )
        campaigns = payload.get("data", [])
    except Exception:
        try:
            campaigns = meta_call("GET", f"{account_id}/campaigns", token, params={"fields": fields, "limit": 100}).get("data", [])
        except Exception:
            campaigns = []
    if not campaigns:
        return None
    return sorted(
        campaigns,
        key=lambda item: str(item.get("updated_time") or item.get("created_time") or item.get("start_time") or ""),
        reverse=True,
    )[0]


def _build_matched_entities(meta_rows: list[dict], creative_rows: list[dict], ga4_rows: list[dict]) -> dict:
    ad_lookup = {}
    for row in creative_rows:
        ad_id = str(row.get("id") or row.get("ad_id") or "").strip()
        if not ad_id:
            continue
        ad_lookup[ad_id] = {
            "campaign_id": row.get("campaign_id"),
            "campaign_name": row.get("campaign_name"),
            "adset_id": row.get("adset_id"),
            "adset_name": row.get("adset_name"),
            "ad_id": ad_id,
            "ad_name": row.get("name") or row.get("ad_name"),
        }

    ga4_by_ad = {}
    for row in ga4_rows:
        ad_id = str(row.get("sessionManualAdContent") or row.get("manualAdContent") or "").strip()
        if not ad_id:
            continue
        current = ga4_by_ad.setdefault(ad_id, {"sessions": 0.0, "activeUsers": 0.0, "engagedSessions": 0.0})
        for metric in list(current.keys()):
            try:
                current[metric] += float(row.get(metric) or 0)
            except (TypeError, ValueError):
                pass

    ads = []
    for ad_id, metrics in ga4_by_ad.items():
        entity = ad_lookup.get(ad_id, {"ad_id": ad_id})
        ads.append({**entity, "ga4_metrics": metrics})

    campaign_lookup = {}
    adset_lookup = {}
    for row in meta_rows + creative_rows:
        if row.get("campaign_id"):
            campaign_lookup[str(row.get("campaign_id"))] = {
                "campaign_id": row.get("campaign_id"),
                "campaign_name": row.get("campaign_name"),
            }
        if row.get("adset_id"):
            adset_lookup[str(row.get("adset_id"))] = {
                "campaign_id": row.get("campaign_id"),
                "campaign_name": row.get("campaign_name"),
                "adset_id": row.get("adset_id"),
                "adset_name": row.get("adset_name"),
            }

    return {
        "campaigns": list(campaign_lookup.values()),
        "adsets": list(adset_lookup.values()),
        "ads": sorted(ads, key=lambda item: item.get("ga4_metrics", {}).get("sessions", 0), reverse=True),
    }


def _ga4_filter_limits(body: JourneyAnalysisRequest) -> list[str]:
    limits = []
    if body.ad_id:
        limits.append("GA4 ad-level filtering is reliable when sessionManualAdContent contains the Meta ad_id, usually from utm_content.")
    if body.adset_id:
        limits.append("GA4 cannot filter by adset_id unless adset_id is sent in UTM or saved as a GA4 custom dimension.")
    if body.campaign_id:
        limits.append("GA4 campaign filtering is reliable only when campaign_id or utm_campaign is present in collected traffic.")
    return limits


def _optional_clarity_behavior(
    body: JourneyAnalysisRequest,
    tenant_id: str,
    matched_entities: dict,
    link_audit: dict,
    data_errors: list[dict],
) -> dict | None:
    if not body.include_clarity:
        return None
    try:
        payload = run_clarity_live_insights_with_fallbacks(tenant_id, body.clarity_num_of_days, ["Campaign", "URL", "Device"])
        rows = normalize_clarity_export(payload)
        summary = summarize_clarity_metrics(rows)
        return {
            "connected": True,
            "num_of_days": payload.get("num_of_days"),
            "dimensions": payload.get("dimensions"),
            "fallback_used": payload.get("fallback_used"),
            "fallback_errors": payload.get("fallback_errors", []),
            "summary_metrics": summary,
            "signals": build_clarity_signals(summary, rows),
            "ad_behavior": build_clarity_ad_behavior(matched_entities, link_audit, rows),
            "linking_note": "Clarity Data Export exposes Campaign/Source/Medium/URL. Ad-level behavior is bridged through GA4 ad_id matching plus Clarity campaign or landing page behavior.",
        }
    except Exception as exc:
        data_errors.append({"source": "clarity", "message": _safe_error(exc)})
        return {"connected": False, "summary_metrics": {}, "signals": []}


def _safe_error(exc: Exception) -> str:
    detail = getattr(exc, "detail", None)
    if detail:
        return str(detail)[:500]
    return str(exc)[:500]


def _journey_decision_label(result: dict, confidence: str) -> dict:
    signals = result.get("signals") or []
    names = {item.get("signal") for item in signals}
    quality = result.get("tracking_quality") or {}
    matching = result.get("matching") or {}
    goal = (result.get("goal_context") or {}).get("primary_goal")

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
        if goal == "messages":
            return {
                "decision": "Hold / Check Messages",
                "primary_reason": "The Meta campaign goal appears to be messages, so missing GA4 purchases or leads is not enough to call it a failed campaign.",
                "next_action": "Judge conversation starts, reply quality, WhatsApp/Messenger follow-up, and add website conversion tracking only if the campaign is meant to produce site leads.",
            }
        if goal in {"traffic", "awareness_engagement"}:
            return {
                "decision": "Hold / Check Goal Fit",
                "primary_reason": "The campaign goal is not clearly direct conversions, so conversion-only judgement would be misleading.",
                "next_action": "Evaluate the campaign against its real objective first, then decide whether conversion tracking is needed for a lower-funnel test.",
            }
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
