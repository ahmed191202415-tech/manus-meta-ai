
from fastapi import APIRouter

from app.schemas.report_requests import (
    SaveExcelReportRequest,
    SavePdfReportRequest,
    SavePptxReportRequest,
    SaveDocxReportRequest,
    SaveHtmlDashboardRequest,
)
from app.reports.excel_report import save_excel_report_local
from app.reports.pdf_report import save_pdf_report_local
from app.reports.pptx_report import save_pptx_report_local
from app.reports.docx_report import save_docx_report_local
from app.reports.html_dashboard import save_html_dashboard_local

router = APIRouter(prefix="/reports", tags=["reports"])


@router.post("/save_excel")
async def save_excel_report(body: SaveExcelReportRequest):
    return save_excel_report_local(body)


@router.post("/save_pdf")
async def save_pdf_report(body: SavePdfReportRequest):
    return save_pdf_report_local(body)


@router.post("/save_pptx")
async def save_pptx_report(body: SavePptxReportRequest):
    return save_pptx_report_local(body)


@router.post("/save_docx")
async def save_docx_report(body: SaveDocxReportRequest):
    return save_docx_report_local(body)


@router.post("/save_html_dashboard")
async def save_html_dashboard(body: SaveHtmlDashboardRequest):
    return save_html_dashboard_local(body)
