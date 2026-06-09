from copy import deepcopy

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.config import ALLOW_ORIGINS, GPT_RESPONSE_MAX_BYTES, PUBLIC_BASE_URL, SESSION_SECRET
from app.core.response_guard import ResponseGuardMiddleware
from app.api.health import router as health_router
from app.api.reports import router as reports_router
from app.api.analysis import router as analysis_router
from app.api.meta_raw import router as meta_router
from app.api.accounts import router as accounts_router
from app.api.insights import router as insights_router
from app.api.campaigns import router as campaigns_router
from app.api.adsets import router as adsets_router
from app.api.ads import router as ads_router
from app.api.creatives import router as creatives_router
from app.api.media import router as media_router
from app.api.audiences import router as audiences_router
from app.api.pixels import router as pixels_router
from app.api.leadgen import router as leadgen_router
from app.api.pages import router as pages_router
from app.api.webhooks import router as webhooks_router
from app.api.dashboard import router as dashboard_router
from app.api.dashboard_builder import router as dashboard_builder_router
from app.api.analysis_dashboard import router as analysis_dashboard_router
from app.api.analysis_docx import router as analysis_docx_router
from app.api.auth_meta import router as auth_meta_router
from app.api.oauth_gpt import router as oauth_gpt_router
from app.api.tenant_portal import router as tenant_portal_router
from app.api.auth_google import router as auth_google_router
from app.api.ga4 import router as ga4_router
from app.api.website_analysis import router as website_analysis_router
from app.api.journey import router as journey_router
from app.api.clarity import router as clarity_router
from app.api.legal import router as legal_router
from app.api.comment_automations import router as comment_automations_router
from app.api.gpt_tools import router as gpt_tools_router

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
}

app = FastAPI(
    title="Super Ad Analysis",
    version="6.1.0",
    servers=openapi_servers,
)


@app.get("/openapi-gpt.json", include_in_schema=False)
def openapi_gpt_schema():
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
            "When unsure which tool to use, call /tools/intent with the user's natural request and known IDs. Follow "
            "its call_next or steps instead of asking the user for technical paths. "
            "For Meta tracking questions, use /tools/meta_tracking. When the user asks which events Meta actually "
            "received, use action=received_pixel_events; do not substitute Custom Conversions. "
            "Use /tools/website for GA4-only site intelligence, /tools/journey for Meta plus GA4 customer-journey "
            "analysis, /tools/clarity for behavior data, and /tools/reports for every supported report format."
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    same_site="lax",
    https_only=True,
)

app.add_middleware(
    ResponseGuardMiddleware,
    max_bytes=GPT_RESPONSE_MAX_BYTES,
    guarded_paths=GPT_DATA_PATHS,
)

app.include_router(health_router)
app.include_router(reports_router)
app.include_router(analysis_router)
app.include_router(meta_router)
app.include_router(accounts_router)
app.include_router(insights_router)
app.include_router(campaigns_router)
app.include_router(adsets_router)
app.include_router(ads_router)
app.include_router(creatives_router)
app.include_router(media_router)
app.include_router(audiences_router)
app.include_router(pixels_router)
app.include_router(leadgen_router)
app.include_router(pages_router)
app.include_router(webhooks_router)
app.include_router(dashboard_router)
app.include_router(dashboard_builder_router)
app.include_router(analysis_dashboard_router)
app.include_router(analysis_docx_router)
app.include_router(auth_meta_router)
app.include_router(oauth_gpt_router)
app.include_router(tenant_portal_router)
app.include_router(auth_google_router)
app.include_router(ga4_router)
app.include_router(website_analysis_router)
app.include_router(journey_router)
app.include_router(clarity_router)
app.include_router(legal_router)
app.include_router(comment_automations_router)
app.include_router(gpt_tools_router)
