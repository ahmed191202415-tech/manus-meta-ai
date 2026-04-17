from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional, List

from app.analytics.preprocessing import fetch_insights_df, infer_previous_range
from app.analytics.metrics import summarize_df
from app.analytics.ranking import build_ranking
from app.analytics.funnel import build_video_funnel
from app.analytics.diagnostics import build_deep_root_cause
from app.reports.docx_report import save_docx_report_local
from app.schemas.report_requests import SaveDocxReportRequest, PdfSectionSpec


router = APIRouter(prefix="/analysis_docx", tags=["analysis_docx"])


class AnalysisDocxRequest(BaseModel):
    account_id: str
    access_token: str
    title: str = "Meta Ads Report"
    subtitle: Optional[str] = None
    level: str = "campaign"
    date_preset: Optional[str] = "last_30d"
    since: Optional[str] = None
    until: Optional[str] = None
    compare_since: Optional[str] = None
    compare_until: Optional[str] = None
    fields: Optional[str] = None
    filters: Optional[str] = None
    sort: Optional[str] = None
    top_n: int = 5
    file_name: Optional[str] = None


@router.post("/build")
async def build_analysis_docx(body: AnalysisDocxRequest):
    current_df = fetch_insights_df(
        body.account_id,
        body.access_token,
        body.level,
        body.fields,
        body.date_preset,
        body.since,
        body.until,
        body.filters,
        body.sort,
    )

    compare_since = body.compare_since
    compare_until = body.compare_until

    if not (compare_since and compare_until):
        auto_since, auto_until = infer_previous_range(body.since, body.until)
        compare_since = compare_since or auto_since
        compare_until = compare_until or auto_until

    import pandas as pd
    compare_df = pd.DataFrame()

    if compare_since and compare_until:
        compare_df = fetch_insights_df(
            body.account_id,
            body.access_token,
            body.level,
            body.fields,
            None,
            compare_since,
            compare_until,
            body.filters,
            body.sort,
        )

    summary = summarize_df(current_df)
    ranking = build_ranking(current_df, body.level, body.top_n)
    funnel = build_video_funnel(current_df)

    root_cause = None
    if not compare_df.empty:
        root_cause = build_deep_root_cause(current_df, compare_df)

    sections: List[PdfSectionSpec] = []

    sections.append(PdfSectionSpec(
        heading="Executive Summary",
        paragraphs=[
            f"Spend: {summary.get('spend')}",
            f"Results: {summary.get('results')}",
            f"CTR: {summary.get('ctr_pct')}%",
            f"CPL: {summary.get('cpl')}",
            f"P75 Rate: {summary.get('p75_rate_pct')}%",
        ]
    ))

    sections.append(PdfSectionSpec(
        heading="Video Funnel",
        paragraphs=[
            f"Impressions: {funnel.get('impressions')}",
            f"P50 Rate: {funnel.get('p50_rate_pct')}%",
            f"P75 Rate: {funnel.get('p75_rate_pct')}%",
            f"Click to Result: {funnel.get('click_to_result_pct')}%",
        ]
    ))

    if ranking.get("top"):
        sections.append(PdfSectionSpec(
            heading="Top Performers",
            table_headers=list(ranking["top"][0].keys()),
            table_rows=[list(item.values()) for item in ranking["top"]]
        ))

    if ranking.get("bottom"):
        sections.append(PdfSectionSpec(
            heading="Bottom Performers",
            table_headers=list(ranking["bottom"][0].keys()),
            table_rows=[list(item.values()) for item in ranking["bottom"]]
        ))

    if root_cause:
        sections.append(PdfSectionSpec(
            heading="Root Cause",
            paragraphs=root_cause.get("interpretation", [])
        ))

    payload = SaveDocxReportRequest(
        file_name=body.file_name,
        title=body.title,
        subtitle=body.subtitle or "Auto-generated DOCX analysis report",
        sections=sections,
    )

    return save_docx_report_local(payload)
