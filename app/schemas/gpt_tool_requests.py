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
