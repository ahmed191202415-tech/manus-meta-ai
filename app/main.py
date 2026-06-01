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

openapi_servers = [{"url": PUBLIC_BASE_URL}] if PUBLIC_BASE_URL else None
GPT_DATA_PATHS = {
    "/comment_automations/manage",
    "/accounts",
    "/insights",
    "/campaigns",
    "/adsets",
    "/ads",
    "/adcreatives",
    "/analysis/run",
    "/ga4/properties",
    "/ga4/select_property",
    "/ga4/custom_report",
    "/clarity/behavior_audit",
    "/ga4/landing_pages",
    "/ga4/traffic_sources",
    "/ga4/devices",
    "/website/analyze",
    "/website/tracking_audit",
    "/website/landing_pages_audit",
    "/website/traffic_quality",
    "/website/device_analysis",
    "/website/conversion_analysis",
    "/journey/analyze",
    "/journey/analyze_from_payload",
    "/journey/utm_audit",
    "/journey/decision",
}

app = FastAPI(
    title="Super Ad Analysis",
    version="6.1.0",
    servers=openapi_servers,
)


@app.get("/openapi-gpt.json", include_in_schema=False)
def openapi_gpt_schema():
    allowed_paths = GPT_DATA_PATHS | {
        "/clarity/connect_token",
        "/reports/save_excel",
        "/reports/save_website_html",
        "/reports/save_website_docx",
        "/reports/save_journey_html",
    }
    allowed_methods = {
        "/campaigns": {"get"},
        "/adsets": {"get"},
        "/ads": {"get"},
        "/adcreatives": {"get"},
    }
    schema = deepcopy(app.openapi())
    schema["info"] = {
        "title": "Super Ad Analysis GPT",
        "version": "1.0.0",
        "description": (
            "Reduced schema for ChatGPT Actions. For Meta and journey analysis, use analyst_brief first: "
            "silently respect goal_context and adset_optimization_goal, present the executive judgement, "
            "strongest evidence, ranked_root_causes, prioritized next actions, and confidence limits. "
            "Do not judge messages campaigns mainly by purchases or website leads."
            " For Facebook Page comments, always use /comment_automations/manage with list_pages, list_posts, "
            "list_comments, subscribe_page, create_rule, list_rules, disable_rule, or delete_rule. "
            "When an automation does not reply, call diagnose_page and inspect webhook deliveries before guessing. "
            "Do not attempt raw Page Graph calls. If response_guard.compacted is true, continue with a smaller "
            "limit or request one specific entity instead of repeating the same broad request. For creatives, list "
            "lightweight rows first and use creative_id with include_details=true for one selected creative only."
        ),
    }
    schema["servers"] = [{"url": PUBLIC_BASE_URL}] if PUBLIC_BASE_URL else []
    filtered_paths = {}
    for path, value in schema.get("paths", {}).items():
        if path not in allowed_paths:
            continue
        methods = allowed_methods.get(path)
        if methods:
            value = {method: spec for method, spec in value.items() if method in methods}
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
