from fastapi import APIRouter

from app.schemas.report_requests import SaveHtmlDashboardRequest
from app.reports.html_dashboard import save_html_dashboard_local

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.post("/save")
async def save_dashboard(body: SaveHtmlDashboardRequest):
    return save_html_dashboard_local(body)
