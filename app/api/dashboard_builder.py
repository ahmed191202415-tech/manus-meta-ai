from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

from app.reports.html_dashboard import save_html_dashboard_local
from app.schemas.report_requests import SaveHtmlDashboardRequest, PdfSectionSpec


router = APIRouter(prefix="/dashboard_builder", tags=["dashboard_builder"])


class DashboardKPI(BaseModel):
    label: str
    value: str
    color: Optional[str] = "#1F4E78"


class DashboardBuilderRequest(BaseModel):
    file_name: Optional[str] = None
    title: str
    subtitle: Optional[str] = None
    kpis: List[DashboardKPI] = Field(default_factory=list)
    sections: List[PdfSectionSpec] = Field(default_factory=list)


@router.post("/build")
async def build_dashboard(body: DashboardBuilderRequest):
    payload = SaveHtmlDashboardRequest(
        file_name=body.file_name,
        title=body.title,
        subtitle=body.subtitle,
        kpis=[k.model_dump() for k in body.kpis],
        sections=body.sections,
    )
    return save_html_dashboard_local(payload)
