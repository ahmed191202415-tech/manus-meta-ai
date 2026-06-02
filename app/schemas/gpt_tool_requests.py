from typing import Any, Literal

from pydantic import BaseModel, Field


class GPTToolRequest(BaseModel):
    action: str = Field(description="Server-side operation to run.")
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Action-specific inputs. The server validates this payload before running the selected operation.",
    )


class GA4ToolRequest(GPTToolRequest):
    action: Literal[
        "list_properties",
        "select_property",
        "custom_report",
        "funnel",
        "realtime",
        "metadata",
        "landing_pages",
        "traffic_sources",
        "events",
        "devices",
    ]
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


class MetaTrackingToolRequest(GPTToolRequest):
    action: Literal["list_pixels", "received_pixel_events", "custom_conversions"]
    account_id: str | None = Field(default=None, description="Meta ad account ID for list_pixels or custom_conversions.")
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
        merged = dict(self.payload)
        for key in (
            "account_id",
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
        ):
            value = getattr(self, key)
            if key in self.model_fields_set and value is not None:
                merged[key] = value
        return merged


class WebsiteToolRequest(GPTToolRequest):
    action: Literal[
        "analyze",
        "tracking_audit",
        "landing_pages_audit",
        "traffic_quality",
        "device_analysis",
        "conversion_analysis",
    ]
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Website analysis inputs: optional tenant_id and property_id, plus start_date, end_date, and limit. "
            'Example: {"property_id":"123","start_date":"30daysAgo","end_date":"today","limit":100}.'
        ),
    )


class JourneyToolRequest(GPTToolRequest):
    action: Literal[
        "analyze",
        "analyze_from_payload",
        "tracking_integrity",
        "ad_to_site_matching",
        "utm_audit",
        "decision",
    ]
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Journey inputs. For analyze, decision, tracking_integrity, or ad_to_site_matching provide "
            "meta_account_id and optional ga4_property_id, campaign_id, campaign_name, adset_id, ad_id, date range, "
            "and level. utm_audit needs meta_account_id. analyze_from_payload accepts meta_rows, creative_rows, and "
            "link_rows when an external connector supplied Meta data."
        ),
    )


class ClarityToolRequest(GPTToolRequest):
    action: Literal["summary", "pages", "behavior_audit"]
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Clarity inputs: optional tenant_id, num_of_days from 1 to 3, dimensions, row_limit, include_raw, and "
            "focus_url for behavior_audit. Keep row_limit small first."
        ),
    )


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
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Report input. website_* and journey_* actions accept {payload:<analysis result>, file_name:<optional>}. "
            "Custom excel accepts sheets; pdf and docx accept title and sections; pptx accepts title and slides; "
            "html_dashboard accepts title, kpis, and sections."
        ),
    )
