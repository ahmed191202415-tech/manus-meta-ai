from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class GA4PropertySelectionRequest(BaseModel):
    tenant_id: str | None = None
    property_id: str = Field(min_length=1)
    property_name: str | None = None


class GA4PropertyListRequest(BaseModel):
    tenant_id: str | None = None


class GA4DateRangeRequest(BaseModel):
    tenant_id: str | None = None
    property_id: str | None = None
    start_date: str = "30daysAgo"
    end_date: str = "today"
    limit: int = Field(default=100, ge=1, le=1000)


class GA4CustomReportRequest(GA4DateRangeRequest):
    dimensions: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)
    order_by: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("dimensions", "metrics")
    @classmethod
    def _not_empty(cls, value: list[str]):
        if not value:
            raise ValueError("At least one item is required.")
        return value


class GA4FunnelStep(BaseModel):
    name: str
    event_name: str


class GA4FunnelReportRequest(GA4DateRangeRequest):
    steps: list[GA4FunnelStep] = Field(default_factory=list)


class WebsiteAnalysisRequest(GA4DateRangeRequest):
    mode: Literal["ga4_only"] = "ga4_only"


class JourneyAnalysisRequest(BaseModel):
    tenant_id: str | None = None
    meta_account_id: str
    ga4_property_id: str | None = None
    campaign_id: str | None = None
    campaign_name: str | None = None
    adset_id: str | None = None
    ad_id: str | None = None
    auto_select_latest_campaign: bool = True
    start_date: str = "30daysAgo"
    end_date: str = "today"
    date_preset: str | None = "last_30d"
    level: Literal["campaign", "adset", "ad"] = "campaign"
    limit: int = Field(default=100, ge=1, le=1000)


class MetaTrackingAuditRequest(BaseModel):
    tenant_id: str | None = None
    meta_account_id: str
    ga4_property_id: str | None = None
    start_date: str = "30daysAgo"
    end_date: str = "today"
    limit: int = Field(default=100, ge=1, le=1000)
