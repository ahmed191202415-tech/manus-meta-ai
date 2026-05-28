from app.reports.website_report import _headers, _rows, _sheet
from app.schemas.report_requests import PdfSectionSpec, SaveExcelReportRequest, SaveHtmlDashboardRequest


def journey_payload_to_html_request(payload: dict, file_name: str | None = None) -> SaveHtmlDashboardRequest:
    metrics = payload.get("journey_metrics") or {}
    matching = payload.get("matching") or {}
    signals = payload.get("signals") or []
    return SaveHtmlDashboardRequest(
        file_name=file_name,
        title="Customer Journey Report",
        subtitle=f"Matching confidence: {matching.get('matching_confidence', 'unavailable')}",
        kpis=[
            {"label": "Meta Clicks", "value": metrics.get("meta_clicks", 0), "color": "#1F4E78"},
            {"label": "GA4 Sessions", "value": metrics.get("ga4_sessions", 0), "color": "#2F75B5"},
            {"label": "Click To Session", "value": metrics.get("click_to_session_rate", 0), "color": "#8A5A00"},
            {"label": "Journey Confidence", "value": metrics.get("journey_confidence_score", 0), "color": "#107C41"},
        ],
        sections=[
            PdfSectionSpec(
                heading="Journey Signals",
                paragraphs=[f"{item.get('signal')} - {item.get('severity')} - {item.get('confidence')}" for item in signals[:12]],
            ),
            PdfSectionSpec(
                heading="Matching Limits",
                paragraphs=matching.get("limits", []),
            ),
            PdfSectionSpec(
                heading="Metrics",
                table_headers=_headers([metrics]),
                table_rows=_rows([metrics]),
            ),
        ],
    )


def journey_payload_to_excel_request(payload: dict, file_name: str | None = None) -> SaveExcelReportRequest:
    return SaveExcelReportRequest(
        file_name=file_name,
        title="Customer Journey Report",
        sheets=[
            _sheet("journey_metrics", [payload.get("journey_metrics") or {}]),
            _sheet("matching", [payload.get("matching") or {}]),
            _sheet("signals", payload.get("signals") or []),
        ],
    )
