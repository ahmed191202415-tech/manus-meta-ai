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
    IntentToolRequest,
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


def _has_any(text: str, *needles: str) -> bool:
    return any(needle in text for needle in needles)


def _clean_dict(payload: dict) -> dict:
    return {
        key: value
        for key, value in payload.items()
        if value not in (None, "", [], {})
    }


def _tool_plan(
    intent: str,
    confidence: str,
    path: str,
    body: dict,
    *,
    needs: list[str] | None = None,
    notes: list[str] | None = None,
    steps: list[dict] | None = None,
) -> dict:
    compact_body = _clean_dict(body)
    result = {
        "ok": True,
        "intent": intent,
        "confidence": confidence,
        "recommended_tool": path,
        "recommended_action": compact_body.get("action"),
        "payload": compact_body,
        "call_next": {"path": path, "body": compact_body},
        "needs": needs or [],
        "notes": notes or [],
    }
    if steps:
        result["steps"] = steps
    return result


def _meta_account_path(account_id: str | None) -> str:
    return normalize_account_id(account_id or "act_<ad_account_id>")


def _ga4_property(body: IntentToolRequest) -> str | None:
    return body.ga4_property_id or body.property_id


def _date_payload(body: IntentToolRequest) -> dict:
    return {
        "tenant_id": body.tenant_id,
        "property_id": _ga4_property(body),
        "start_date": body.start_date or "30daysAgo",
        "end_date": body.end_date or "today",
        "limit": body.limit,
    }


def _default_ga4_custom_payload(body: IntentToolRequest) -> dict:
    dimensions = body.dimensions or ["date"]
    metrics = body.metrics or ["sessions", "activeUsers"]
    payload = {
        **_date_payload(body),
        "dimensions": dimensions,
        "metrics": metrics,
    }
    if body.page_path_contains:
        payload["page_path_contains"] = body.page_path_contains
    if body.event_names:
        payload["dimension_filters"] = [
            {"dimension": "eventName", "operator": "in_list", "values": body.event_names}
        ]
    return payload


def _campaign_insights_steps(body: IntentToolRequest) -> list[dict]:
    account_path = _meta_account_path(body.meta_account_id)
    campaign_id = body.campaign_id or "<campaign_id>"
    date_preset = body.date_preset or "last_7d"
    return [
        {
            "reason": "Discover available ad accounts when the account is not known.",
            "path": "/meta/query",
            "body": {
                "path": "me/adaccounts",
                "params": {
                    "fields": "id,name,account_id,account_status,currency,timezone_name",
                    "limit": 100,
                },
            },
        },
        {
            "reason": "Find the latest or requested campaign, including objective for correct diagnosis.",
            "path": "/meta/query",
            "body": {
                "path": f"{account_path}/campaigns",
                "params": {
                    "fields": "id,name,status,effective_status,objective,created_time,updated_time,start_time,stop_time",
                    "limit": 100,
                },
            },
        },
        {
            "reason": "Read performance from the campaign object directly after the campaign ID is known.",
            "path": "/meta/query",
            "body": {
                "path": f"{campaign_id}/insights",
                "params": {
                    "date_preset": date_preset,
                    "fields": (
                        "campaign_id,campaign_name,objective,spend,impressions,reach,clicks,"
                        "inline_link_clicks,outbound_clicks,actions,cpc,cpm,ctr,date_start,date_stop"
                    ),
                },
            },
        },
    ]


@router.post(
    "/intent",
    summary="Route natural request",
    description="Maps Arabic or English user requests to the best tool, action, payload, and next steps. Use first when unsure.",
)
async def intent_tool(body: IntentToolRequest):
    text = body.request.strip().lower()
    property_id = _ga4_property(body)

    if _has_any(text, "path exploration", "مسار", "path analysis", "user journey path"):
        return {
            "ok": True,
            "intent": "ga4_path_exploration",
            "confidence": "high",
            "supported_directly": False,
            "reason": "GA4 Data API does not expose the full Explore Path Exploration report through this compact tool.",
            "recommended_alternatives": [
                _tool_plan(
                    "ga4_custom_page_event_report",
                    "medium",
                    "/tools/ga4",
                    {
                        "action": "custom_report",
                        **_default_ga4_custom_payload(body),
                        "dimensions": body.dimensions or ["pagePathPlusQueryString", "eventName"],
                        "metrics": body.metrics or ["eventCount", "activeUsers"],
                    },
                )["call_next"],
                _tool_plan(
                    "ga4_funnel",
                    "medium",
                    "/tools/ga4",
                    {
                        "action": "funnel",
                        "tenant_id": body.tenant_id,
                        "property_id": property_id,
                        "start_date": body.start_date or "30daysAgo",
                        "end_date": body.end_date or "today",
                        "steps": [{"name": name, "event_name": name} for name in body.event_names],
                        "limit": body.limit,
                    },
                    needs=[] if body.event_names else ["event_names"],
                )["call_next"],
            ],
            "notes": ["For exact path exploration, export to BigQuery later or use GA4 Explore UI."],
        }

    if _has_any(text, "funnel", "runfunnelreport", "فنل", "قمع"):
        return _tool_plan(
            "ga4_funnel",
            "high",
            "/tools/ga4",
            {
                "action": "funnel",
                "tenant_id": body.tenant_id,
                "property_id": property_id,
                "start_date": body.start_date or "30daysAgo",
                "end_date": body.end_date or "today",
                "steps": [{"name": name, "event_name": name} for name in body.event_names],
                "limit": body.limit,
            },
            needs=[] if body.event_names else ["event_names"],
            notes=["Use event_names to build funnel steps. Do not fetch all events first unless the user asks for discovery."],
        )

    if _has_any(text, "property", "properties", "بروبرتي", "خصائص", "analytics account"):
        action = "select_property" if property_id else "list_properties"
        return _tool_plan(
            "ga4_property_setup",
            "high",
            "/tools/ga4",
            {
                "action": action,
                "tenant_id": body.tenant_id,
                "property_id": property_id,
            },
            needs=[] if body.tenant_id else ["tenant_id"],
        )

    if _has_any(text, "verify-otp", "otp", "page", "landing", "صفحة", "صفحات"):
        return _tool_plan(
            "ga4_custom_page_report",
            "high",
            "/tools/ga4",
            {
                "action": "custom_report",
                **_default_ga4_custom_payload(body),
                "dimensions": body.dimensions or ["pagePathPlusQueryString"],
                "metrics": body.metrics or ["screenPageViews", "activeUsers", "eventCount"],
                "page_path_contains": body.page_path_contains or ("verify-otp" if "otp" in text else None),
            },
            needs=[] if property_id else ["property_id or selected GA4 property"],
        )

    if _has_any(text, "event", "events", "ايفنت", "احداث", "أحداث"):
        if _has_any(text, "pixel", "meta pixel", "بيكسل"):
            return _tool_plan(
                "meta_received_pixel_events",
                "high",
                "/tools/meta_tracking",
                {
                    "action": "received_pixel_events",
                    "pixel_id": body.pixel_id,
                    "start_date": body.start_date,
                    "end_date": body.end_date,
                    "fallback_days": 28,
                    "include_raw": False,
                },
                needs=[] if body.pixel_id else ["pixel_id"],
                notes=["Use this for events actually received by Meta Pixel, not Custom Conversions."],
            )
        return _tool_plan(
            "ga4_events_report",
            "high",
            "/tools/ga4",
            {
                "action": "custom_report",
                **_default_ga4_custom_payload(body),
                "dimensions": body.dimensions or ["date", "eventName"],
                "metrics": body.metrics or ["eventCount", "activeUsers"],
            },
            needs=[] if property_id else ["property_id or selected GA4 property"],
        )

    if _has_any(text, "tracking", "تتبع", "utm", "attribution", "انالتكس", "analytics", "ga4"):
        return _tool_plan(
            "website_or_journey_tracking",
            "medium",
            "/tools/journey" if body.meta_account_id or body.campaign_id else "/tools/website",
            {
                "action": "tracking_integrity" if body.meta_account_id or body.campaign_id else "tracking_audit",
                "tenant_id": body.tenant_id,
                "meta_account_id": body.meta_account_id,
                "ga4_property_id": property_id,
                "campaign_id": body.campaign_id,
                "campaign_name": body.campaign_name,
                "start_date": body.start_date or "30daysAgo",
                "end_date": body.end_date or "today",
                "date_preset": body.date_preset,
                "limit": body.limit,
            },
            needs=[] if property_id else ["property_id or selected GA4 property"],
            notes=["Compare Meta and GA4 without treating clicks, sessions, leads, and conversions as the same metric."],
        )

    if _has_any(text, "clarity", "كلاريتي", "heatmap", "click", "scroll", "behavior"):
        return _tool_plan(
            "clarity_behavior",
            "high",
            "/tools/clarity",
            {
                "action": "behavior_audit",
                "tenant_id": body.tenant_id,
                "num_of_days": 1,
                "focus_url": body.page_path_contains,
                "row_limit": min(body.limit, 100),
            },
            notes=["Clarity export APIs provide aggregated insight rows, not raw visual heatmap pixels."],
        )

    if _has_any(text, "lead form", "form_leads", "leads", "فورم", "ليد"):
        action = "form_leads" if body.form_id else "lead_forms"
        return _tool_plan(
            "meta_lead_ads",
            "high",
            "/tools/meta_tracking",
            {
                "action": action,
                "page_id": body.page_id,
                "form_id": body.form_id,
                "limit": body.limit,
            },
            needs=[] if body.page_id and (action == "lead_forms" or body.form_id) else ["page_id", "form_id when reading leads"],
            notes=["If Meta rejects the call, run diagnose_lead_access to see missing page permissions."],
        )

    if _has_any(text, "comment", "reply", "كومنت", "تعليق", "رد تلقائي", "ماسنجر"):
        return _tool_plan(
            "comment_automation",
            "medium",
            "/comment_automations/manage",
            {
                "action": "list_rules",
                "tenant_id": body.tenant_id,
                "page_id": body.page_id,
                "limit": body.limit,
            },
            needs=[] if body.page_id else ["page_id"],
            notes=["Use diagnose_page and webhook deliveries when a rule does not reply automatically."],
        )

    if _has_any(text, "report", "تقرير", "pdf", "excel", "pptx", "docx"):
        return _tool_plan(
            "report_generation",
            "medium",
            "/tools/reports",
            {"action": "docx", "payload": {}},
            notes=["Generate the analysis payload first, then pass it to /tools/reports in the requested format."],
        )

    if _has_any(text, "meta", "facebook", "campaign", "adset", "ad ", "اعلان", "إعلان", "حملة", "ادسيت"):
        target = body.ad_id or body.adset_id or body.campaign_id
        level = "ad" if body.ad_id else "adset" if body.adset_id else "campaign"
        if target:
            return _tool_plan(
                f"meta_{level}_insights",
                "high",
                "/meta/smart_insights",
                {
                    "account_id": body.meta_account_id,
                    "campaign_id": body.campaign_id,
                    "adset_id": body.adset_id,
                    "ad_id": body.ad_id,
                    "date_preset": body.date_preset or "last_7d",
                    "level": level,
                    "limit": body.limit,
                },
                notes=["Use the smart insights tool first because it retries with safer fields and includes objective context."],
            )
        return _tool_plan(
            "meta_campaign_discovery_and_insights",
            "medium",
            "/meta/query",
            _campaign_insights_steps(body)[0]["body"],
            needs=[] if body.meta_account_id else ["meta_account_id for the second step"],
            notes=["Use the steps in order. Do not ask the user for Graph paths."],
            steps=_campaign_insights_steps(body),
        )

    return _tool_plan(
        "general_analysis_router",
        "low",
        "/analysis/run",
        {"tenant_id": body.tenant_id, "payload": {"user_request": body.request}},
        notes=["If this is a platform data request, retry /tools/intent with IDs or keywords from the user's message."],
    )


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
        "Unified GA4 tool. Supports property setup, custom reports, runFunnelReport aliases, realtime, metadata, "
        "events, landing pages, traffic sources, and devices. Use direct fields, not nested payload, when possible."
    ),
)
async def ga4_tool(body: GA4ToolRequest, request: Request):
    action = _normalize_ga4_action(body.action)
    payload = body.merged_payload()
    if action == "list_properties":
        return await ga4.ga4_properties(request, payload.get("tenant_id"))
    if action == "select_property":
        return await ga4.ga4_select_property(_validated(GA4PropertySelectionRequest, payload), request)
    if action == "custom_report":
        return await ga4.ga4_custom_report(_validated(GA4CustomReportRequest, payload), request)
    if action == "funnel":
        return await ga4.ga4_funnel(_validated(GA4FunnelReportRequest, payload), request)
    if action == "realtime":
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
    if action == "metadata":
        return await ga4.ga4_metadata(request, payload.get("tenant_id"), payload.get("property_id"))
    return await _ga4_standard_report(action, payload, request)


def _normalize_ga4_action(action: str) -> str:
    aliases = {
        "runFunnelReport": "funnel",
        "run_funnel_report": "funnel",
        "funnel_report": "funnel",
        "ga4_funnel": "funnel",
    }
    return aliases.get(action, action)


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
