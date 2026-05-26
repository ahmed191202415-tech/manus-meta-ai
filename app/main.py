from copy import deepcopy

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.config import ALLOW_ORIGINS, PUBLIC_BASE_URL, SESSION_SECRET
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
from app.api.legal import router as legal_router

openapi_servers = [{"url": PUBLIC_BASE_URL}] if PUBLIC_BASE_URL else None

app = FastAPI(
    title="Super Ad Analysis",
    version="6.1.0",
    servers=openapi_servers,
)


@app.get("/openapi-gpt.json", include_in_schema=False)
def openapi_gpt_schema():
    allowed_paths = {
        "/health",
        "/meta/request",
        "/accounts",
        "/insights",
        "/campaigns",
        "/adsets",
        "/ads",
        "/adcreatives",
        "/adimages",
        "/advideos",
        "/pages",
        "/page_posts",
        "/page_comments",
        "/page_comments/{comment_id}/reply",
        "/page_comments/{comment_id}/hide",
        "/analysis/run",
        "/analysis_dashboard/build",
        "/analysis_docx/build",
        "/ga4/properties",
        "/ga4/select_property",
        "/reports/save_excel",
        "/reports/save_pdf",
        "/reports/save_pptx",
        "/reports/save_docx",
        "/reports/save_html_dashboard",
    }
    schema = deepcopy(app.openapi())
    schema["info"] = {
        "title": "Super Ad Analysis GPT",
        "version": "1.0.0",
        "description": "Reduced schema for ChatGPT Actions with stable Meta, analysis, reports, and page operations.",
    }
    schema["servers"] = [{"url": PUBLIC_BASE_URL}] if PUBLIC_BASE_URL else []
    schema["paths"] = {
        path: value
        for path, value in schema.get("paths", {}).items()
        if path in allowed_paths
    }
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
app.include_router(legal_router)
