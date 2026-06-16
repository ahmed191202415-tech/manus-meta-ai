from typing import Any, Literal

from pydantic import BaseModel, Field


class GPTToolRequest(BaseModel):
    action: str = Field(description="Server-side operation to run.")
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Action-specific inputs. The server validates this payload before running the selected operation.",
    )

    def merge_direct_fields(self, *keys: str) -> dict[str, Any]:
        merged = dict(self.payload)
        for key in keys:
            value = getattr(self, key)
            if key in self.model_fields_set and value is not None:
                merged[key] = value
        return merged


class IntentToolRequest(BaseModel):
    request: str = Field(min_length=2, description="Natural user request in Arabic or English.")
    tenant_id: str | None = Field(default=None, description="Optional tenant ID.")
    meta_account_id: str | None = Field(default=None, description="Optional Meta ad account ID.")
    ga4_property_id: str | None = Field(default=None, description="Optional GA4 Property ID.")
    property_id: str | None = Field(default=None, description="Optional GA4 Property ID alias.")
    campaign_id: str | None = Field(default=None, description="Optional Meta Campaign ID.")
    campaign_name: str | None = Field(default=None, description="Optional Meta Campaign name.")
    adset_id: str | None = Field(default=None, description="Optional Meta Ad Set ID.")
    ad_id: str | None = Field(default=None, description="Optional Meta Ad ID.")
    page_id: str | None = Field(default=None, description="Optional Facebook Page ID.")
    pixel_id: str | None = Field(default=None, description="Optional Meta Pixel ID.")
    form_id: str | None = Field(default=None, description="Optional Lead Form ID.")
    start_date: str | None = Field(default=None, description="Optional start date.")
    end_date: str | None = Field(default=None, description="Optional end date.")
    date_preset: str | None = Field(default=None, description="Optional Meta date preset.")
    dimensions: list[str] = Field(default_factory=list, description="Optional GA4 dimensions.")
    metrics: list[str] = Field(default_factory=list, description="Optional GA4 metrics.")
    event_names: list[str] = Field(default_factory=list, description="Optional event names for reports or funnels.")
    page_path_contains: str | None = Field(default=None, description="Optional page URL/path fragment.")
    limit: int = Field(default=100, ge=1, le=1000, description="Maximum rows.")


class GA4ToolRequest(GPTToolRequest):
    action: Literal[
        "list_properties",
        "select_property",
        "custom_report",
        "funnel",
        "runFunnelReport",
        "run_funnel_report",
        "funnel_report",
        "ga4_funnel",
        "realtime",
        "metadata",
        "landing_pages",
        "traffic_sources",
        "events",
        "devices",
    ]
    tenant_id: str | None = Field(default=None, description="Optional tenant ID.")
    property_id: str | None = Field(default=None, description="GA4 Property ID. Required unless a selected Property is saved.")
    property_name: str | None = Field(default=None, description="Optional GA4 Property display name for select_property.")
    start_date: str | None = Field(default=None, description="GA4 start date such as 30daysAgo or YYYY-MM-DD.")
    end_date: str | None = Field(default=None, description="GA4 end date such as today or YYYY-MM-DD.")
    dimensions: list[str] | str | None = Field(default=None, description="GA4 dimensions. For realtime, a comma-separated string is also accepted.")
    metrics: list[str] | None = Field(default=None, description="GA4 metrics for custom_report.")
    page_path_contains: str | None = Field(default=None, description="Optional page URL/path fragment for custom_report.")
    dimension_filters: list[dict[str, Any]] | None = Field(default=None, description="Typed GA4 dimension filters for custom_report.")
    metric_filters: list[dict[str, Any]] | None = Field(default=None, description="Typed GA4 metric filters for custom_report.")
    sort: list[dict[str, Any]] | None = Field(default=None, description="Typed GA4 sorting for custom_report.")
    filters: dict[str, Any] | None = Field(default=None, description="Advanced GA4 filters for custom_report.")
    order_by: list[dict[str, Any]] | None = Field(default=None, description="Advanced GA4 ordering for custom_report.")
    offset: int | None = Field(default=None, ge=0, le=100000, description="GA4 custom_report row offset.")
    metric_aggregations: list[Literal["TOTAL", "MINIMUM", "MAXIMUM", "COUNT"]] | None = Field(default=None, description="Optional GA4 aggregations.")
    steps: list[dict[str, Any]] | None = Field(default=None, description="Funnel steps with name and event_name.")
    limit: int | None = Field(default=None, ge=1, le=1000, description="Maximum report rows.")
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Inputs for the selected GA4 action. custom_report example: "
            '{"property_id":"123","start_date":"30daysAgo","end_date":"today","dimensions":["eventName"],'
            '"metrics":["eventCount"],"dimension_filters":[],"sort":[],"limit":50}. '
            "Standard reports accept tenant_id, property_id, start_date, end_date, and limit. "
            "select_property accepts property_id and optional property_name. realtime accepts optional dimensions."
        ),
    )

    def merged_payload(self) -> dict[str, Any]:
        return self.merge_direct_fields(
            "tenant_id", "property_id", "property_name", "start_date", "end_date", "dimensions", "metrics",
            "page_path_contains", "dimension_filters", "metric_filters", "sort", "filters", "order_by", "offset",
            "metric_aggregations", "steps", "limit",
        )


class MetaTrackingToolRequest(GPTToolRequest):
    action: Literal[
        "list_pixels",
        "received_pixel_events",
        "custom_conversions",
        "diagnose_lead_access",
        "lead_forms",
        "form_leads",
    ]
    account_id: str | None = Field(default=None, description="Meta ad account ID for list_pixels or custom_conversions.")
    page_id: str | None = Field(default=None, description="Facebook Page ID for Lead Forms or Page-scoped reads.")
    form_id: str | None = Field(default=None, description="Meta Lead Gen Form ID for form_leads.")
    pixel_id: str | None = Field(default=None, description="Meta Pixel ID for received_pixel_events.")
    start_date: str | None = Field(default=None, description="Optional YYYY-MM-DD start date for received Pixel events.")
    end_date: str | None = Field(default=None, description="Optional inclusive YYYY-MM-DD end date for received Pixel events.")
    fallback_days: int = Field(default=28, ge=1, le=90, description="Expand an empty Pixel event lookup to this many days.")
    include_raw: bool = Field(default=False, description="Include raw Pixel stats rows for debugging.")
    fields: str | None = Field(default=None, description="Optional Meta fields for list_pixels or custom_conversions.")
    limit: int = Field(default=100, ge=1, le=500, description="Maximum rows for list operations.")
    after: str | None = Field(default=None, description="Optional Meta pagination cursor for list_pixels.")
    fetch_all: bool = Field(default=False, description="Fetch multiple Pixel pages when true.")
    max_pages: int = Field(default=10, ge=1, le=50, description="Maximum Pixel pages when fetch_all is true.")
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Backward-compatible nested inputs. Prefer the direct fields beside action."
        ),
    )

    def merged_payload(self) -> dict[str, Any]:
        return self.merge_direct_fields(
            "account_id",
            "page_id",
            "form_id",
            "pixel_id",
            "start_date",
            "end_date",
            "fallback_days",
            "include_raw",
            "fields",
            "limit",
            "after",
            "fetch_all",
            "max_pages",
        )


class WebsiteToolRequest(GPTToolRequest):
    action: Literal[
        "analyze",
        "tracking_audit",
        "landing_pages_audit",
        "traffic_quality",
        "device_analysis",
        "conversion_analysis",
    ]
    tenant_id: str | None = Field(default=None, description="Optional tenant ID.")
    property_id: str | None = Field(default=None, description="GA4 Property ID. Uses the selected Property when omitted.")
    start_date: str | None = Field(default=None, description="GA4 start date such as 30daysAgo or YYYY-MM-DD.")
    end_date: str | None = Field(default=None, description="GA4 end date such as today or YYYY-MM-DD.")
    limit: int | None = Field(default=None, ge=1, le=1000, description="Maximum rows per website report.")
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Website analysis inputs: optional tenant_id and property_id, plus start_date, end_date, and limit. "
            'Example: {"property_id":"123","start_date":"30daysAgo","end_date":"today","limit":100}.'
        ),
    )

    def merged_payload(self) -> dict[str, Any]:
        return self.merge_direct_fields("tenant_id", "property_id", "start_date", "end_date", "limit")


class JourneyToolRequest(GPTToolRequest):
    action: Literal[
        "analyze",
        "analyze_from_payload",
        "tracking_integrity",
        "ad_to_site_matching",
        "utm_audit",
        "decision",
    ]
    tenant_id: str | None = Field(default=None, description="Optional tenant ID.")
    meta_account_id: str | None = Field(default=None, description="Meta ad account ID.")
    ga4_property_id: str | None = Field(default=None, description="Optional GA4 Property ID.")
    campaign_id: str | None = Field(default=None, description="Optional Meta Campaign ID.")
    campaign_name: str | None = Field(default=None, description="Optional Meta Campaign name.")
    adset_id: str | None = Field(default=None, description="Optional Meta Ad Set ID.")
    ad_id: str | None = Field(default=None, description="Optional Meta Ad ID.")
    auto_select_latest_campaign: bool | None = Field(default=None, description="Select the latest campaign when no campaign filter is provided.")
    include_clarity: bool | None = Field(default=None, description="Include Clarity behavior when available.")
    clarity_num_of_days: int | None = Field(default=None, ge=1, le=3, description="Clarity lookback days.")
    start_date: str | None = Field(default=None, description="GA4 start date.")
    end_date: str | None = Field(default=None, description="GA4 end date.")
    date_preset: str | None = Field(default=None, description="Meta date preset.")
    level: Literal["campaign", "adset", "ad"] | None = Field(default=None, description="Meta analysis level.")
    meta_rows: list[dict[str, Any]] | None = Field(default=None, description="Optional external Meta rows for analyze_from_payload.")
    creative_rows: list[dict[str, Any]] | None = Field(default=None, description="Optional external creative rows.")
    link_rows: list[dict[str, Any]] | None = Field(default=None, description="Optional external tracking-link rows.")
    limit: int | None = Field(default=None, ge=1, le=1000, description="Maximum rows.")
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Journey inputs. For analyze, decision, tracking_integrity, or ad_to_site_matching provide "
            "meta_account_id and optional ga4_property_id, campaign_id, campaign_name, adset_id, ad_id, date range, "
            "and level. utm_audit needs meta_account_id. analyze_from_payload accepts meta_rows, creative_rows, and "
            "link_rows when an external connector supplied Meta data."
        ),
    )

    def merged_payload(self) -> dict[str, Any]:
        return self.merge_direct_fields(
            "tenant_id", "meta_account_id", "ga4_property_id", "campaign_id", "campaign_name", "adset_id", "ad_id",
            "auto_select_latest_campaign", "include_clarity", "clarity_num_of_days", "start_date", "end_date",
            "date_preset", "level", "meta_rows", "creative_rows", "link_rows", "limit",
        )


class ClarityToolRequest(GPTToolRequest):
    action: Literal["summary", "pages", "behavior_audit"]
    tenant_id: str | None = Field(default=None, description="Optional tenant ID.")
    num_of_days: int | None = Field(default=None, ge=1, le=3, description="Clarity lookback days.")
    dimensions: list[str] | None = Field(default=None, max_length=3, description="Optional Clarity dimensions.")
    include_raw: bool | None = Field(default=None, description="Include raw Clarity rows.")
    row_limit: int | None = Field(default=None, ge=0, le=100, description="Maximum returned rows.")
    focus_url: str | None = Field(default=None, description="Optional URL fragment for behavior_audit.")
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Clarity inputs: optional tenant_id, num_of_days from 1 to 3, dimensions, row_limit, include_raw, and "
            "focus_url for behavior_audit. Keep row_limit small first."
        ),
    )

    def merged_payload(self) -> dict[str, Any]:
        return self.merge_direct_fields("tenant_id", "num_of_days", "dimensions", "include_raw", "row_limit", "focus_url")


class ReportToolRequest(GPTToolRequest):
    action: Literal[
        "excel",
        "pdf",
        "pptx",
        "docx",
        "html_dashboard",
        "website_html",
        "website_excel",
        "website_pdf",
        "website_docx",
        "journey_html",
        "journey_excel",
        "journey_pdf",
        "journey_docx",
    ]
    file_name: str | None = Field(default=None, description="Optional output file name.")
    title: str | None = Field(default=None, description="Report title for custom formats.")
    subtitle: str | None = Field(default=None, description="Optional report subtitle.")
    sheets: list[dict[str, Any]] | None = Field(default=None, description="Excel sheet definitions.")
    sections: list[dict[str, Any]] | None = Field(default=None, description="PDF, DOCX, or HTML sections.")
    slides: list[dict[str, Any]] | None = Field(default=None, description="PPTX slide definitions.")
    kpis: list[dict[str, Any]] | None = Field(default=None, description="HTML dashboard KPI definitions.")
    report_payload: dict[str, Any] | None = Field(default=None, description="Website or Journey analysis result for intelligence formats.")
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Report input. website_* and journey_* actions accept {payload:<analysis result>, file_name:<optional>}. "
            "Custom excel accepts sheets; pdf and docx accept title and sections; pptx accepts title and slides; "
            "html_dashboard accepts title, kpis, and sections."
        ),
    )

    def merged_payload(self) -> dict[str, Any]:
        merged = self.merge_direct_fields("file_name", "title", "subtitle", "sheets", "sections", "slides", "kpis")
        if "report_payload" in self.model_fields_set and self.report_payload is not None:
            merged["payload"] = self.report_payload
        return merged


class DashboardToolRequest(GPTToolRequest):
    action: Literal["create_dashboard", "update_dashboard", "update_snapshot", "list_dashboards", "delete_dashboard"]
    tenant_id: str | None = Field(default=None, description="Tenant ID for the dashboard owner.")
    dashboard_id: str | None = Field(default=None, description="Dashboard ID for update, snapshot, or delete.")
    title: str | None = Field(default=None, description="Dashboard title.")
    description: str | None = Field(default=None, description="Dashboard description.")
    filters: list[dict[str, Any]] | None = Field(default=None, description="Dashboard filter definitions.")
    data_sources: list[dict[str, Any]] | None = Field(default=None, description="Dashboard data source definitions.")
    widgets: list[dict[str, Any]] | None = Field(default=None, description="Dashboard widget definitions.")
    layout: dict[str, Any] | None = Field(default=None, description="Optional layout configuration.")
    initial_snapshot: dict[str, Any] | None = Field(default=None, description="Initial data snapshot for create_dashboard.")
    snapshot: dict[str, Any] | None = Field(default=None, description="Data snapshot for update_snapshot.")
    refresh_policy: dict[str, Any] | None = Field(default=None, description="Refresh policy such as on_open, hourly, or daily.")
    limit: int | None = Field(default=None, ge=1, le=200, description="Maximum dashboards to list.")
    payload: dict[str, Any] = Field(default_factory=dict, description="Backward-compatible nested inputs.")

    def merged_payload(self) -> dict[str, Any]:
        return self.merge_direct_fields(
            "tenant_id",
            "dashboard_id",
            "title",
            "description",
            "filters",
            "data_sources",
            "widgets",
            "layout",
            "initial_snapshot",
            "snapshot",
            "refresh_policy",
            "limit",
        )
