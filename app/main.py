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
    title="Manus Sovereign Meta Server",
    version="6.1.0",
    servers=openapi_servers,
)


@app.get("/openapi-gpt.json", include_in_schema=False)
def openapi_gpt_schema():
    """Compact ChatGPT Actions schema.

    Keep the GPT smart and dynamic by exposing the raw Meta request tool plus only
    the core analysis/report/page helpers. The backend can still have more routes.
    """
    allowed_paths = {
        "/health",
        "/meta/request",
        "/accounts",
        "/insights",
        "/analysis/run",
        "/analysis_dashboard/build",
        "/analysis_docx/build",
        "/reports/save_excel",
        "/reports/save_pdf",
        "/reports/save_pptx",
        "/reports/save_docx",
        "/reports/save_html_dashboard",
        "/pages",
        "/page_posts",
        "/page_comments",
        "/page_comments/{comment_id}/reply",
        "/page_comments/{comment_id}/hide",
    }
    schema = deepcopy(app.openapi())
    schema["info"] = {
        "title": "Manus Meta Server Lite",
        "version": "1.0.0",
        "description": "Reduced schema for ChatGPT Actions with core Meta, analysis, reports, and page operations.",
    }
    schema["servers"] = [{"url": EFFECTIVE_PUBLIC_BASE_URL}]

    filtered_paths = {}
    operation_ids = {
        ("/health", "get"): ("health", "Health", "Server health"),
        ("/meta/request", "post"): ("meta_request", "Raw Meta Request", "Meta response"),
        ("/accounts", "get"): ("list_accounts", "List Accounts", "Accounts list"),
        ("/insights", "get"): ("get_insights", "Get Insights", "Insights response"),
        ("/analysis/run", "post"): ("analysis_run", "Analysis Run", "Analysis result"),
        ("/analysis_dashboard/build", "post"): ("analysis_dashboard_build", "Build Analysis Dashboard", "HTML dashboard file result"),
        ("/analysis_docx/build", "post"): ("analysis_docx_build", "Build Analysis DOCX", "DOCX report file result"),
        ("/reports/save_excel", "post"): ("save_excel_report", "Save Excel Report", "Excel file result"),
        ("/reports/save_pdf", "post"): ("save_pdf_report", "Save PDF Report", "PDF file result"),
        ("/reports/save_pptx", "post"): ("save_pptx_report", "Save PPTX Report", "PPTX file result"),
        ("/reports/save_docx", "post"): ("save_docx_report", "Save DOCX Report", "DOCX file result"),
        ("/reports/save_html_dashboard", "post"): ("save_html_dashboard", "Save HTML Dashboard", "HTML dashboard result"),
        ("/pages", "get"): ("list_pages", "List Pages", "Pages list"),
        ("/page_posts", "get"): ("list_page_posts", "List Page Posts", "Page posts list"),
        ("/page_posts", "post"): ("create_page_post", "Create Page Post", "Create page post result"),
        ("/page_comments", "get"): ("list_page_comments", "List Page Comments", "Page comments list"),
        ("/page_comments/{comment_id}/reply", "post"): ("reply_to_comment", "Reply To Comment", "Reply result"),
        ("/page_comments/{comment_id}/hide", "post"): ("hide_comment", "Hide Comment", "Hide comment result"),
    }
    for path, value in schema.get("paths", {}).items():
        if path not in allowed_paths:
            continue
        path_item = deepcopy(value)
        for method, operation in list(path_item.items()):
            if not isinstance(operation, dict):
                continue
            op_id, summary, response_desc = operation_ids.get((path, method), (operation.get("operationId") or f"{method}_{path}", operation.get("summary") or path, "Successful Response"))
            operation["operationId"] = op_id
            operation["summary"] = summary
            operation.pop("description", None)
            operation.pop("tags", None)
            operation.pop("security", None)
            responses = operation.setdefault("responses", {})
            responses["200"] = {"description": response_desc}
            responses.pop("422", None)
        filtered_paths[path] = path_item
    schema["paths"] = filtered_paths

    # Compact components: keep only schemas referenced by the Lite paths and make
    # RawMetaRequest simple so ChatGPT keeps using it dynamically.
    components = schema.setdefault("components", {})
    schemas = components.get("schemas", {})
    keep = {
        "RawMetaRequest",
        "AnalysisRunRequest",
        "AnalysisDashboardRequest",
        "AnalysisDocxRequest",
        "SaveExcelReportRequest",
        "ExcelSheetSpec",
        "SavePdfReportRequest",
        "PdfSectionSpec",
        "SavePptxReportRequest",
        "PptSlideSpec",
        "SaveDocxReportRequest",
        "SaveHtmlDashboardRequest",
        "PagePostCreateRequest",
        "CommentReplyRequest",
        "CommentHideRequest",
    }
    components["schemas"] = {k: v for k, v in schemas.items() if k in keep}
    components["schemas"]["RawMetaRequest"] = {
        "type": "object",
        "properties": {
            "method": {"type": "string", "enum": ["GET", "POST", "DELETE"], "default": "GET"},
            "path": {"type": "string"},
            "params": {"type": "object", "additionalProperties": True, "default": {}},
            "data": {"type": "object", "additionalProperties": True, "default": {}},
        },
        "required": ["path"],
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
app.include_router(campaign_analysis_router)
app.include_router(auth_meta_router)
app.include_router(oauth_gpt_router)
app.include_router(tenant_portal_router)
