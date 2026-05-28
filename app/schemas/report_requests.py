
from typing import Optional, Any, List
from pydantic import BaseModel, Field


class ExcelSheetSpec(BaseModel):
    name: str = "Sheet1"
    headers: List[str] = Field(default_factory=list)
    rows: List[List[Any]] = Field(default_factory=list)


class SaveExcelReportRequest(BaseModel):
    file_name: Optional[str] = None
    title: Optional[str] = None
    sheets: List[ExcelSheetSpec]


class PdfSectionSpec(BaseModel):
    heading: Optional[str] = None
    paragraphs: List[str] = Field(default_factory=list)
    table_headers: List[str] = Field(default_factory=list)
    table_rows: List[List[Any]] = Field(default_factory=list)


class SavePdfReportRequest(BaseModel):
    file_name: Optional[str] = None
    title: str
    subtitle: Optional[str] = None
    sections: List[PdfSectionSpec] = Field(default_factory=list)


class PptSlideSpec(BaseModel):
    title: str
    bullets: List[str] = Field(default_factory=list)
    table_headers: List[str] = Field(default_factory=list)
    table_rows: List[List[Any]] = Field(default_factory=list)


class SavePptxReportRequest(BaseModel):
    file_name: Optional[str] = None
    title: str
    subtitle: Optional[str] = None
    slides: List[PptSlideSpec] = Field(default_factory=list)


class SaveDocxReportRequest(BaseModel):
    file_name: Optional[str] = None
    title: str
    subtitle: Optional[str] = None
    sections: List[PdfSectionSpec] = Field(default_factory=list)


class SaveHtmlDashboardRequest(BaseModel):
    file_name: Optional[str] = None
    title: str
    subtitle: Optional[str] = None
    kpis: List[dict] = Field(default_factory=list)
    sections: List[PdfSectionSpec] = Field(default_factory=list)


class IntelligenceReportRequest(BaseModel):
    file_name: Optional[str] = None
    payload: dict = Field(default_factory=dict)
