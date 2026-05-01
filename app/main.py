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
from app.api.campaign_analysis import router as campaign_analysis_router
from app.api.auth_meta import router as auth_meta_router
from app.api.oauth_gpt import router as oauth_gpt_router
from app.api.tenant_portal import router as tenant_portal_router

DEFAULT_PUBLIC_BASE_URL = "https://manus-meta-ai-production.up.railway.app"
EFFECTIVE_PUBLIC_BASE_URL = PUBLIC_BASE_URL or DEFAULT_PUBLIC_BASE_URL
openapi_servers = [{"url": EFFECTIVE_PUBLIC_BASE_URL}]

app = FastAPI(
    title="Super Ad Analysis",
    version="6.1.0",
    servers=openapi_servers,
)


@app.get("/openapi-gpt.json", include_in_schema=False)
def openapi_gpt_schema():
    """Small no-$ref OpenAPI schema optimized for ChatGPT Actions import."""
    server_url = EFFECTIVE_PUBLIC_BASE_URL
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Super Ad Analysis GPT",
            "version": "1.0.0",
            "description": "ChatGPT Actions schema for Meta Ads data, live campaign analysis, reports, and page operations.",
        },
        "servers": [{"url": server_url}],
        "paths": {
            "/health": {
                "get": {
                    "operationId": "health",
                    "summary": "Check API health",
                    "responses": {"200": {"description": "API is healthy"}},
                }
            },
            "/accounts": {
                "get": {
                    "operationId": "list_ad_accounts",
                    "summary": "List connected Meta ad accounts",
                    "responses": {"200": {"description": "Meta ad accounts"}},
                }
            },
            "/campaigns": {
                "get": {
                    "operationId": "list_campaigns",
                    "summary": "List Meta campaigns for an ad account",
                    "parameters": [
                        {"name": "account_id", "in": "query", "required": True, "schema": {"type": "string"}},
                        {"name": "limit", "in": "query", "required": False, "schema": {"type": "integer", "default": 50}},
                    ],
                    "responses": {"200": {"description": "Campaign list"}},
                }
            },
            "/insights": {
                "get": {
                    "operationId": "get_insights",
                    "summary": "Get Meta Ads insights",
                    "parameters": [
                        {"name": "account_id", "in": "query", "required": True, "schema": {"type": "string"}},
                        {"name": "level", "in": "query", "required": False, "schema": {"type": "string", "default": "campaign"}},
                        {"name": "date_preset", "in": "query", "required": False, "schema": {"type": "string"}},
                        {"name": "since", "in": "query", "required": False, "schema": {"type": "string"}},
                        {"name": "until", "in": "query", "required": False, "schema": {"type": "string"}},
                    ],
                    "responses": {"200": {"description": "Insights data"}},
                }
            },
            "/analysis/campaign": {
                "post": {
                    "operationId": "analyze_campaign",
                    "summary": "Analyze one Meta Ads campaign using live Meta API data",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["account_id", "campaign_id"],
                                    "properties": {
                                        "account_id": {"type": "string", "description": "Meta ad account id, with or without act_"},
                                        "campaign_id": {"type": "string", "description": "Meta campaign id"},
                                        "since": {"type": "string", "description": "Start date YYYY-MM-DD"},
                                        "until": {"type": "string", "description": "End date YYYY-MM-DD"},
                                        "date_preset": {"type": "string", "description": "Meta date preset such as last_7d or last_30d"},
                                        "compare_since": {"type": "string"},
                                        "compare_until": {"type": "string"},
                                        "level": {"type": "string", "default": "ad", "enum": ["account", "campaign", "adset", "ad"]},
                                        "question": {"type": "string", "default": "حلل هذه الحملة"},
                                        "fields": {"type": "string"},
                                        "deep": {"type": "boolean", "default": False},
                                    },
                                }
                            }
                        },
                    },
                    "responses": {"200": {"description": "Campaign intelligence analysis"}},
                }
            },
            "/analysis/run": {
                "post": {
                    "operationId": "run_analysis",
                    "summary": "Run general Meta Ads analysis",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["account_id"],
                                    "properties": {
                                        "account_id": {"type": "string"},
                                        "analysis_type": {"type": "string", "default": "intelligence_diagnostics"},
                                        "level": {"type": "string", "default": "campaign"},
                                        "date_preset": {"type": "string"},
                                        "since": {"type": "string"},
                                        "until": {"type": "string"},
                                        "top_n": {"type": "integer", "default": 10},
                                    },
                                }
                            }
                        },
                    },
                    "responses": {"200": {"description": "Analysis result"}},
                }
            },
            "/reports/save_pdf": {
                "post": {
                    "operationId": "save_pdf_report",
                    "summary": "Save a PDF report",
                    "requestBody": {"required": True, "content": {"application/json": {"schema": {"type": "object", "properties": {"title": {"type": "string"}, "content": {"type": "string"}, "html": {"type": "string"}, "markdown": {"type": "string"}, "filename": {"type": "string"}}, "additionalProperties": True}}}},
                    "responses": {"200": {"description": "Saved report"}},
                }
            },
            "/reports/save_docx": {
                "post": {
                    "operationId": "save_docx_report",
                    "summary": "Save a DOCX report",
                    "requestBody": {"required": True, "content": {"application/json": {"schema": {"type": "object", "properties": {"title": {"type": "string"}, "content": {"type": "string"}, "html": {"type": "string"}, "markdown": {"type": "string"}, "filename": {"type": "string"}}, "additionalProperties": True}}}},
                    "responses": {"200": {"description": "Saved report"}},
                }
            },
        },
    }

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
app.include_router(campaign_analysis_router)
app.include_router(auth_meta_router)
app.include_router(oauth_gpt_router)
app.include_router(tenant_portal_router)
