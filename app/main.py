from copy import deepcopy

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.config import ALLOW_ORIGINS, GPT_RESPONSE_MAX_BYTES, PUBLIC_BASE_URL, SESSION_SECRET
from app.core.response_guard import ResponseGuardMiddleware
from app.api.router_registry import include_api_routers

openapi_servers = [{"url": PUBLIC_BASE_URL}] if PUBLIC_BASE_URL else None
GPT_DATA_PATHS = {
    "/comment_automations/manage",
    "/meta/query",
    "/meta/request",
    "/meta/smart_insights",
    "/analysis/run",
    "/tools/intent",
    "/tools/ga4",
    "/tools/meta_tracking",
    "/tools/website",
    "/tools/journey",
    "/tools/clarity",
    "/tools/reports",
    "/tools/dashboards",
    "/api/dashboard-definitions",
    "/api/dashboard-definitions/v2",
    "/api/dashboard-definitions/{dashboard_id}",
    "/api/dashboard-definitions/v2/{dashboard_id}",
    "/api/dashboard-code/v1",
    "/api/dashboard-code/v1/{dashboard_id}",
    "/api/dashboard-runtime/query",
    "/api/dashboard-runtime/v2/workflow",
    "/api/dashboard-runtime/events/discover",
    "/dashboards/custom/{dashboard_id}",
    "/dashboards/code/{dashboard_id}",
    "/api/journey/funnel",
    "/api/journey/stage-detail",
    "/api/journey/trend",
    "/api/journey/comparison",
}

def _gpt_openapi_schema(app: FastAPI) -> dict:
    allowed_paths = GPT_DATA_PATHS
    schema = deepcopy(app.openapi())
    schema["info"] = {
        "title": "Super Ad Analysis GPT",
        "version": "1.0.0",
        "description": (
            "Compact schema for ChatGPT Actions. Each exposed tool is a broad dispatcher backed by validated "
            "server-side operations. Use the smallest number of calls needed for the user's question. "
            "For Meta and journey analysis, use analyst_brief first: "
            "silently respect goal_context and adset_optimization_goal, present the executive judgement, "
            "strongest evidence, ranked_root_causes, prioritized next actions, and confidence limits. "
            "Do not judge messages campaigns mainly by purchases or website leads."
            " For Facebook Page comments, always use /comment_automations/manage with list_pages, list_posts, "
            "list_comments, subscribe_page, create_rule, list_rules, disable_rule, or delete_rule. "
            "When an automation does not reply, call diagnose_page and inspect webhook deliveries before guessing. "
            "To reply on every new comment across all Page posts, create_rule with page_id and omit post_id. "
            "For ad posts, create rules with ad_id when known. For an existing rule, use set_rule_ad_scope with its "
            "ad_id so verified internal Meta story IDs are linked automatically. For any remaining dark post or "
            "unpublished post that Meta cannot verify, use list_unmapped_posts and ask for confirmation before "
            "link_post_alias. "
            "Do not attempt raw Page Graph calls. If response_guard.compacted is true, continue with a smaller "
            "limit or request one specific entity instead of repeating the same broad request. For creatives, list "
            "lightweight rows first and use creative_id with include_details=true for one selected creative only. "
            "For GA4 setup, custom reports, standard reports, funnel, realtime, or metadata, use /tools/ga4 with "
            "the matching action. GA4 funnels are supported through action=funnel and aliases runFunnelReport, "
            "run_funnel_report, funnel_report, or ga4_funnel. For a GA4 page lookup, use action=custom_report with a small limit and "
            'page_path_contains="the-page-fragment" instead of fetching all page URLs. '
            "For any GA4 custom question, choose the needed dimensions and metrics and use the simplified "
            "dimension_filters, metric_filters, sort, offset, and metric_aggregations fields. "
            "Do not invent a sort field inside filters and do not fetch all rows before filtering."
            " For every natural-language Meta question, use /meta/query as the primary dynamic Meta Graph read tool. "
            "Infer the required Graph path and small field list from the user's question without asking the user for "
            "technical paths. Discover with me/adaccounts, act_<account_id>/campaigns, <campaign_id>/adsets, or "
            "<adset_id>/ads when IDs are not known. For performance reads, prefer direct <campaign_id>/insights, "
            "<adset_id>/insights, or <ad_id>/insights once the entity is known. Request only the fields needed for "
            "the answer and expand with a second focused /meta/query call when needed. The /meta/query tool is "
            "read-only: never use it for write operations. Treat Pixel or Events Manager permission errors as "
            "separate capability limits; they do not mean campaign, ad set, or ad insights are unavailable. "
            "Use /meta/request only when the user explicitly asks to create, edit, publish, pause, resume, delete, "
            "or reply through Meta. Confirm the intended write action with the user before sending it. Never use "
            "/meta/request for ordinary analysis or discovery reads. For Facebook Page post or comment operations, "
            "provide page_id to /meta/query or /meta/request so the server selects the Page access token. The dynamic "
            "tools also cover media, lead forms, leads, pixels, audiences, and Instagram Graph paths when requested. "
            "For a new Page or Ad engagement Custom Audience, first read an existing working audience rule. Then POST "
            "to act_<account_id>/customaudiences with source_audience_id and audience_retention_days; the server clones "
            "the accepted rule and removes customer-file-only fields instead of inventing event names. "
            "When unsure which tool to use, call /tools/intent with the user's natural request and known IDs. Follow "
            "its call_next or steps instead of asking the user for technical paths. "
            "For Meta tracking questions, use /tools/meta_tracking. When the user asks which events Meta actually "
            "received, use action=received_pixel_events; do not substitute Custom Conversions. "
            "Use /tools/website for GA4-only site intelligence, /tools/journey for Meta plus GA4 customer-journey "
            "analysis, /tools/clarity for behavior data, /tools/reports for report files, and /tools/dashboards "
            "to create dynamic dashboard links that stay attached to each tenant portal. "
            "For every new dashboard section, use the universal runtime v2 workflow: inspect capabilities, validate "
            "a declarative query plan, preview live values and their sources in chat, wait for explicit user confirmation, "
            "then publish the section with the returned confirmation_token. Never publish a section directly from guessed "
            "metrics or a static snapshot. Runtime plans may compose Meta, GA4, Clarity, and safe transforms for filters, "
            "KPIs, funnels, charts, tables, comparisons, and alerts without adding a new endpoint per dashboard request. "
            "The dashboard tool is also a general tenant backend: create_dataset, upsert_records, query_dataset, delete_records, list_datasets, "
            "and delete_dataset store arbitrary JSON without requiring a new backend table per user request. Link a "
            "dataset to any dashboard with dashboard_id or a data source whose source is dataset. Use render_mode=code "
            "with html, css, javascript, and data_contract for a fully custom persistent dashboard. For custom live dashboards, "
            "use /api/dashboard-runtime/connectors to inspect available sources, /api/dashboard-definitions/v2 to save "
            "a manifest, /api/dashboard-runtime/events/discover to inspect available Meta actions before mapping "
            "events, /api/dashboard-runtime/query to run a chart query, /dashboards/custom/{dashboard_id} to open "
            "a manifest-rendered dashboard page. For fully custom dashboard UI, use /api/dashboard-code/v1 with "
            "html, css, and javascript, then open /dashboards/code/{dashboard_id}; the page can call "
            "window.ALLINGPT.runQuery(query_id, filters). Use /api/journey/* endpoints for the "
            "customer-journey dashboard data. Never map offsite_conversion.fb_pixel_custom to a dashboard stage unless "
            "the saved manifest explicitly sets that action_type with explicitly_mapped_by_gpt=true."
        ),
    }
    schema["servers"] = [{"url": PUBLIC_BASE_URL}] if PUBLIC_BASE_URL else []
    filtered_paths = {}
    for path, value in schema.get("paths", {}).items():
        if path not in allowed_paths:
            continue
        filtered_paths[path] = value
    schema["paths"] = filtered_paths
    return schema


def create_app() -> FastAPI:
    application = FastAPI(
        title="Super Ad Analysis",
        version="6.1.0",
        servers=openapi_servers,
    )

    @application.get("/openapi-gpt.json", include_in_schema=False)
    def openapi_gpt_schema():
        return _gpt_openapi_schema(application)

    application.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOW_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=True,
    )
    application.add_middleware(
        SessionMiddleware,
        secret_key=SESSION_SECRET,
        same_site="lax",
        https_only=True,
    )
    application.add_middleware(
        ResponseGuardMiddleware,
        max_bytes=GPT_RESPONSE_MAX_BYTES,
        guarded_paths=GPT_DATA_PATHS,
    )
    include_api_routers(application)
    return application


app = create_app()


def openapi_gpt_schema() -> dict:
    """Backward-compatible programmatic access to the exported app schema."""
    return _gpt_openapi_schema(app)
