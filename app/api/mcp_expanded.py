"""Explicit allowlisted MCP adapters around the existing tenant-aware FastAPI endpoints.

No caller-supplied API paths, arbitrary tenant IDs, or raw credentials are
accepted. Each call runs through the application's existing route validation.
"""
from __future__ import annotations

import json
from typing import Any

import httpx
from fastapi import HTTPException

# Map each tool to exactly one existing, reviewed application endpoint.
# Writes are isolated from reads and require a separate OAuth scope.
SPECS = {
    "route_marketing_intent": {
        "title": "Understand marketing requests",
        "description": "Route a natural-language analytics question to the best available Meta, GA4, Clarity, journey, or dashboard workflow. Does not execute account changes.",
        "path": "/tools/intent",
        "actions": None,
        "read": True,
    },
    "meta_graph_read": {
        "title": "Read any authorized Meta Graph resource",
        "description": "Read Meta ad accounts, campaigns, ad sets, ads, creatives, insight edges, Pages, posts, comments, lead forms, pixels, audiences or Instagram via a focused Graph path. GET only. First discover IDs when necessary.",
        "path": "/meta/query",
        "actions": None,
        "read": True,
    },
    "meta_smart_insights": {
        "title": "Analyze Meta Ads performance",
        "description": "Run Meta campaign/ad set/ad insight analysis using account_id and optional date_preset, since/until, level, campaign_id, adset_id, or ad_id.",
        "path": "/meta/smart_insights",
        "actions": None,
        "read": True,
    },
    "analyze_ad_campaigns": {
        "title": "Run comprehensive advertising diagnostics",
        "description": "Run the existing analysis engine: goals, Meta campaign performance, comparisons, anomaly detection, profitability, forecast and executive recommendations. Use verified Meta metrics.",
        "path": "/analysis/run",
        "actions": None,
        "read": True,
    },
    "meta_tracking_read": {
        "title": "Inspect Meta Pixels and lead tracking",
        "description": "Inspect pixels, received pixel events, conversions, lead forms, lead access and leads using action and payload.",
        "path": "/tools/meta_tracking",
        "actions": ["list_pixels", "received_pixel_events", "custom_conversions", "diagnose_lead_access", "lead_forms", "form_leads"],
        "read": True,
    },
    "ga4_read": {
        "title": "Read Google Analytics 4",
        "description": "Run GA4 custom reports, standard reports, funnels, realtime, metadata, events, landing pages, device and traffic data. Action plus payload.",
        "path": "/tools/ga4",
        "actions": ["list_properties", "custom_report", "funnel", "runFunnelReport", "run_funnel_report", "funnel_report", "ga4_funnel", "realtime", "metadata", "landing_pages", "traffic_sources", "events", "devices"],
        "read": True,
    },
    "ga4_select_property": {
        "title": "Select default Google Analytics property",
        "description": "Save the Google Analytics 4 property for this authorized tenant after user confirmation.",
        "path": "/tools/ga4",
        "actions": ["select_property"],
        "read": False,
    },
    "clarity_read": {
        "title": "Microsoft Clarity behavior analytics",
        "description": "Get Clarity summary, pages and behavior audit using action and payload.",
        "path": "/tools/clarity",
        "actions": ["summary", "pages", "behavior_audit"],
        "read": True,
    },
    "website_read": {
        "title": "Website and landing-page intelligence",
        "description": "Analyze GA4 website traffic, devices, page quality, conversions and tracking using action and payload.",
        "path": "/tools/website",
        "actions": ["analyze", "tracking_audit", "landing_pages_audit", "traffic_quality", "device_analysis", "conversion_analysis"],
        "read": True,
    },
    "journey_read": {
        "title": "Meta and GA4 customer journey",
        "description": "Analyze customer journey, tracking, Meta-to-site matching, UTMs, and decisions using action and payload.",
        "path": "/tools/journey",
        "actions": ["analyze", "analyze_from_payload", "tracking_integrity", "ad_to_site_matching", "utm_audit", "decision"],
        "read": True,
    },
    "facebook_comments_read": {
        "title": "Inspect Facebook Page comments and automation",
        "description": "List Facebook Pages, posts, comments, automation rules and logs; diagnose webhook deliveries and unmapped ad posts.",
        "path": "/comment_automations/manage",
        "actions": ["list_pages", "list_posts", "list_comments", "list_rules", "list_logs", "diagnose_page", "list_unmapped_posts", "list_post_aliases"],
        "read": True,
    },
    "facebook_comments_manage": {
        "title": "Manage Page subscriptions and comment automation",
        "description": "After explicit user approval: subscribe Pages, create/enable/disable/delete automatic reply rules, link verified ad posts, or change ad scopes. Never modify without confirmation.",
        "path": "/comment_automations/manage",
        "actions": ["subscribe_page", "create_rule", "enable_rule", "disable_rule", "delete_rule", "link_post_alias", "set_rule_ad_scope"],
        "read": False,
    },
    "meta_graph_write": {
        "title": "Make confirmed Meta Ads or Page changes",
        "description": "For user-approved changes only: create/edit/pause/resume/delete campaigns, ad sets, ads, audiences, Page posts and comments using the existing Meta Graph write endpoint. Uses method POST, PATCH, or DELETE, with path and data.",
        "path": "/meta/request",
        "actions": None,
        "read": False,
    },
    "report_generate": {
        "title": "Generate a marketing report",
        "description": "Generate Excel, PDF, DOCX, PPTX, HTML, website or journey reports from results. File links are ephemeral on Vercel until persistent export storage is configured.",
        "path": "/tools/reports",
        "actions": ["excel", "pdf", "pptx", "docx", "html_dashboard", "website_html", "website_excel", "website_pdf", "website_docx", "journey_html", "journey_excel", "journey_pdf", "journey_docx"],
        "read": False,
    },
    "dashboards_read": {
        "title": "Read dashboards and tenant datasets",
        "description": "List existing dashboards, list tenant datasets, and query dataset records. No writes.",
        "path": "/tools/dashboards",
        "actions": ["list_dashboards", "list_datasets", "query_dataset"],
        "read": True,
    },
    "dashboards_manage": {
        "title": "Create or edit confirmed dashboards",
        "description": "After user approval create/edit/delete dashboards, refresh snapshots and create/edit/delete the authorized tenant datasets.",
        "path": "/tools/dashboards",
        "actions": ["create_dashboard", "update_dashboard", "update_snapshot", "refresh_dashboard", "delete_dashboard", "create_dataset", "upsert_records", "delete_records", "delete_dataset"],
        "read": False,
    },
    "dashboard_runtime_read": {
        "title": "Dynamic dashboard live-data planning",
        "description": "Inspect available sources, validate a backend plan, preview live data or execute a dashboard plan; preview must precede publication.",
        "path": "/api/dashboard-runtime/v2/workflow",
        "actions": ["capabilities", "validate", "preview", "execute"],
        "read": True,
    },
    "dashboard_runtime_publish": {
        "title": "Publish verified dashboard section",
        "description": "Only after explicit user approval and an actual verified preview; provide confirmation_token from preview, query plan and section.",
        "path": "/api/dashboard-runtime/v2/workflow",
        "actions": ["publish_section"],
        "read": False,
    },
}


def _schema(spec: dict[str, Any]) -> dict:
    properties = {
        "payload": {
            "type": "object",
            "description": "Action-specific JSON object. Use fields documented in the application's existing API. Do not include credentials or a different tenant_id.",
            "additionalProperties": True,
        },
    }
    required = ["payload"]
    if spec["actions"] is not None:
        properties["action"] = {"type": "string", "enum": spec["actions"]}
        required.insert(0, "action")
    if not spec["read"]:
        properties["confirmed"] = {
            "type": "boolean",
            "description": "True only after this user has explicitly confirmed this exact change.",
        }
        required.append("confirmed")
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


EXTRA_TOOLS = [
    {
        "name": name,
        "title": spec["title"],
        "description": spec["description"],
        "inputSchema": _schema(spec),
        "annotations": {
            "readOnlyHint": spec["read"],
            "destructiveHint": not spec["read"],
            "openWorldHint": True,
        },
        "securitySchemes": [
            {"type": "oauth2", "scopes": ["ads.read"] if spec["read"] else ["ads.write"]}
        ],
    }
    for name, spec in SPECS.items()
]


def _check_tenant(value: Any, tenant_id: str, depth: int = 0) -> None:
    """Reject cross-tenant identifiers even when nested in reports or plans."""
    if depth > 15:
        raise HTTPException(422, "Request too deep")
    if isinstance(value, dict):
        for key, part in value.items():
            if key in {"tenant_id", "owner_tenant_id"} and part not in (None, "", tenant_id):
                raise HTTPException(403, "Tenant mismatch")
            _check_tenant(part, tenant_id, depth + 1)
    elif isinstance(value, list):
        for part in value:
            _check_tenant(part, tenant_id, depth + 1)


async def invoke_extra_tool(name: str, args: dict, bearer: str, tenant_id: str) -> Any:
    spec = SPECS.get(name)
    if not spec:
        raise HTTPException(404, "Unknown MCP tool")
    if not isinstance(args, dict) or not isinstance(args.get("payload"), dict):
        raise HTTPException(422, "Expected a payload JSON object")
    payload = dict(args["payload"])
    _check_tenant(payload, tenant_id)
    if spec["actions"] is not None:
        action = args.get("action")
        if action not in spec["actions"]:
            raise HTTPException(400, "Unsupported or disallowed action")
        payload["action"] = action
    if not spec["read"] and args.get("confirmed") is not True:
        raise HTTPException(403, "Explicit approval is required for write operations")
    # Existing tenant-aware handlers normally accept tenant_id as a top-level input.
    # For actions using a nested payload, apply it there too so GA4 and Clarity
    # never default to the globally latest connected account.
    if name not in {"route_marketing_intent", "meta_graph_read", "meta_smart_insights", "analyze_ad_campaigns", "meta_tracking_read", "meta_graph_write", "report_generate"}:
        payload["tenant_id"] = tenant_id
        if isinstance(payload.get("payload"), dict):
            payload["payload"] = {**payload["payload"], "tenant_id": tenant_id}

    # Route in-process through the same FastAPI dependencies and validation, not
    # an external HTTP call (which may hit deployment protection or SSO).
    from app.main import app
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://mcp-backend.internal",
        timeout=90,
    ) as client:
        response = await client.post(spec["path"], json=payload, headers={
            "Authorization": "Bearer " + bearer,
            "Accept": "application/json",
        })
    try:
        data = response.json()
    except ValueError:
        data = {"message": "Non-JSON response from application"}
    if response.status_code >= 400:
        raise HTTPException(response.status_code, data.get("detail") if isinstance(data, dict) else "Request failed")
    return data
