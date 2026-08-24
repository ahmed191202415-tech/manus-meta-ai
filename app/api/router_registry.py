from __future__ import annotations

from fastapi import FastAPI

from app.api.accounts import router as accounts_router
from app.api.ads import router as ads_router
from app.api.adsets import router as adsets_router
from app.api.analysis import router as analysis_router
from app.api.analysis_dashboard import router as analysis_dashboard_router
from app.api.analysis_docx import router as analysis_docx_router
from app.api.audiences import router as audiences_router
from app.api.auth_google import router as auth_google_router
from app.api.auth_meta import router as auth_meta_router
from app.api.campaigns import router as campaigns_router
from app.api.clarity import router as clarity_router
from app.api.comment_automations import router as comment_automations_router
from app.api.creatives import router as creatives_router
from app.api.dashboard import router as dashboard_router
from app.api.dashboard_builder import router as dashboard_builder_router
from app.api.dashboard_console import router as dashboard_console_router
from app.api.dashboard_runtime import router as universal_dashboard_runtime_router
from app.api.dynamic_dashboards import router as dynamic_dashboards_router
from app.api.ga4 import router as ga4_router
from app.api.gpt_tools import router as gpt_tools_router
from app.api.health import router as health_router
from app.api.insights import router as insights_router
from app.api.journey import router as journey_router
from app.api.journey_dashboard_v7 import router as journey_dashboard_v7_router
from app.api.leadgen import router as leadgen_router
from app.api.legal import router as legal_router
from app.api.media import router as media_router
from app.api.meta_raw import router as meta_router
from app.api.oauth_gpt import router as oauth_gpt_router
from app.api.pages import router as pages_router
from app.api.pixels import router as pixels_router
from app.api.reports import router as reports_router
from app.api.tenant_portal import router as tenant_portal_router
from app.api.webhooks import router as webhooks_router
from app.api.website_analysis import router as website_analysis_router


API_ROUTERS = (
    health_router,
    reports_router,
    analysis_router,
    meta_router,
    accounts_router,
    insights_router,
    campaigns_router,
    adsets_router,
    ads_router,
    creatives_router,
    media_router,
    audiences_router,
    pixels_router,
    leadgen_router,
    pages_router,
    webhooks_router,
    dashboard_router,
    dashboard_builder_router,
    dashboard_console_router,
    dynamic_dashboards_router,
    journey_dashboard_v7_router,
    analysis_dashboard_router,
    analysis_docx_router,
    auth_meta_router,
    oauth_gpt_router,
    tenant_portal_router,
    auth_google_router,
    ga4_router,
    website_analysis_router,
    journey_router,
    clarity_router,
    legal_router,
    comment_automations_router,
    gpt_tools_router,
    universal_dashboard_runtime_router,
)


def include_api_routers(app: FastAPI) -> None:
    for router in API_ROUTERS:
        app.include_router(router)
