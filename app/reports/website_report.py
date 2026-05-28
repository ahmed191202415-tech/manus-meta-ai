from app.schemas.report_requests import PdfSectionSpec, SaveExcelReportRequest, SaveHtmlDashboardRequest


def website_payload_to_html_request(payload: dict, file_name: str | None = None) -> SaveHtmlDashboardRequest:
    summary = payload.get("summary_metrics") or {}
    quality = payload.get("tracking_quality") or {}
    signals = payload.get("signals") or []
    top_entities = payload.get("top_entities") or {}
    return SaveHtmlDashboardRequest(
        file_name=file_name,
        title="Website Performance Report",
        subtitle=f"Mode: {payload.get('mode', 'ga4_only')} | Property: {payload.get('property_id', '')}",
        kpis=[
            {"label": "Sessions", "value": summary.get("sessions", 0), "color": "#1F4E78"},
            {"label": "Engagement Rate", "value": summary.get("engagement_rate", 0), "color": "#2F75B5"},
            {"label": "Conversion Rate", "value": summary.get("conversion_rate", 0), "color": "#8A5A00"},
            {"label": "Tracking Score", "value": quality.get("tracking_score", quality.get("score", 0)), "color": "#107C41"},
        ],
        sections=[
            PdfSectionSpec(
                heading="Signals",
                paragraphs=[f"{item.get('signal')} - {item.get('severity')} - {item.get('confidence')}" for item in signals[:12]],
            ),
            PdfSectionSpec(
                heading="Top Landing Pages",
                table_headers=_headers(top_entities.get("landing_pages", [])),
                table_rows=_rows(top_entities.get("landing_pages", [])),
            ),
            PdfSectionSpec(
                heading="Top Traffic Sources",
                table_headers=_headers(top_entities.get("traffic_sources", [])),
                table_rows=_rows(top_entities.get("traffic_sources", [])),
            ),
        ],
    )


def website_payload_to_excel_request(payload: dict, file_name: str | None = None) -> SaveExcelReportRequest:
    top_entities = payload.get("top_entities") or {}
    return SaveExcelReportRequest(
        file_name=file_name,
        title="Website Performance Report",
        sheets=[
            _sheet("summary", [payload.get("summary_metrics") or {}]),
            _sheet("signals", payload.get("signals") or []),
            _sheet("landing_pages", top_entities.get("landing_pages", [])),
            _sheet("traffic_sources", top_entities.get("traffic_sources", [])),
            _sheet("devices", top_entities.get("devices", [])),
        ],
    )


def _headers(items: list[dict]) -> list[str]:
    keys = []
    for item in items:
        for key in item.keys():
            if key not in keys:
                keys.append(key)
    return keys[:12]


def _rows(items: list[dict]) -> list[list]:
    headers = _headers(items)
    return [[item.get(header) for header in headers] for item in items[:50]]


def _sheet(name: str, items: list[dict]):
    from app.schemas.report_requests import ExcelSheetSpec

    return ExcelSheetSpec(name=name, headers=_headers(items), rows=_rows(items))
