from typing import Any, Literal

from pydantic import BaseModel, Field


class DashboardFilterSpec(BaseModel):
    key: str
    label: str | None = None
    type: Literal["date_range", "select", "text", "number"] = "select"
    default: Any = None
    options: list[dict[str, Any]] = Field(default_factory=list)


class DashboardDataSourceSpec(BaseModel):
    source: Literal["meta", "ga4", "clarity", "journey", "manual"] = "manual"
    name: str
    query: dict[str, Any] = Field(default_factory=dict)
    refresh: Literal["on_open", "hourly", "daily", "manual"] = "on_open"


class DashboardWidgetSpec(BaseModel):
    id: str
    title: str
    type: Literal["kpi", "table", "line", "bar", "funnel", "text"] = "table"
    source: str | None = None
    metric: str | None = None
    dimensions: list[str] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)


class DynamicDashboardCreateRequest(BaseModel):
    tenant_id: str | None = Field(default=None, description="Tenant ID. Uses the active portal session when omitted.")
    title: str
    description: str | None = None
    filters: list[DashboardFilterSpec] = Field(default_factory=list)
    data_sources: list[DashboardDataSourceSpec] = Field(default_factory=list)
    widgets: list[DashboardWidgetSpec] = Field(default_factory=list)
    layout: dict[str, Any] = Field(default_factory=dict)
    initial_snapshot: dict[str, Any] = Field(default_factory=dict)
    refresh_policy: dict[str, Any] = Field(default_factory=lambda: {"mode": "on_open"})


class DynamicDashboardUpdateRequest(BaseModel):
    tenant_id: str | None = None
    title: str | None = None
    description: str | None = None
    filters: list[DashboardFilterSpec] | None = None
    data_sources: list[DashboardDataSourceSpec] | None = None
    widgets: list[DashboardWidgetSpec] | None = None
    layout: dict[str, Any] | None = None
    refresh_policy: dict[str, Any] | None = None
    status: Literal["active", "paused", "deleted"] | None = None


class DynamicDashboardSnapshotRequest(BaseModel):
    tenant_id: str | None = None
    snapshot: dict[str, Any] = Field(default_factory=dict)
