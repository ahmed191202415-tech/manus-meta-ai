from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class DashboardFilterSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    key: str
    label: str | None = None
    type: str = "select"
    default: Any = None
    options: list[dict[str, Any]] = Field(default_factory=list)


class DashboardDataSourceSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    source: str = "manual"
    name: str
    query: dict[str, Any] = Field(default_factory=dict)
    refresh: Literal["on_open", "hourly", "daily", "manual"] = "on_open"


class DashboardWidgetSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    title: str
    type: str = "table"
    source: str | None = None
    metric: str | None = None
    dimensions: list[str] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)


class DynamicDashboardCreateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    tenant_id: str | None = Field(default=None, description="Tenant ID. Uses the active portal session when omitted.")
    title: str
    description: str | None = None
    filters: list[DashboardFilterSpec] = Field(default_factory=list)
    data_sources: list[DashboardDataSourceSpec] = Field(default_factory=list)
    widgets: list[DashboardWidgetSpec] = Field(default_factory=list)
    layout: dict[str, Any] = Field(default_factory=dict)
    initial_snapshot: dict[str, Any] = Field(default_factory=dict)
    refresh_policy: dict[str, Any] = Field(default_factory=lambda: {"mode": "on_open"})
    render_mode: Literal["manifest", "code"] = "manifest"
    html: str | None = None
    css: str | None = None
    javascript: str | None = None
    data_contract: dict[str, Any] = Field(default_factory=dict)


class DynamicDashboardUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    tenant_id: str | None = None
    title: str | None = None
    description: str | None = None
    filters: list[DashboardFilterSpec] | None = None
    data_sources: list[DashboardDataSourceSpec] | None = None
    widgets: list[DashboardWidgetSpec] | None = None
    layout: dict[str, Any] | None = None
    refresh_policy: dict[str, Any] | None = None
    status: Literal["active", "paused", "deleted"] | None = None
    render_mode: Literal["manifest", "code"] | None = None
    html: str | None = None
    css: str | None = None
    javascript: str | None = None
    data_contract: dict[str, Any] | None = None


class DynamicDashboardSnapshotRequest(BaseModel):
    tenant_id: str | None = None
    snapshot: dict[str, Any] = Field(default_factory=dict)


class DynamicDashboardRefreshRequest(BaseModel):
    tenant_id: str | None = None
    snapshot: dict[str, Any] | None = None
    force: bool = False


class DashboardDatasetCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    tenant_id: str | None = None
    dashboard_id: str | None = None
    name: str
    description: str | None = None
    dataset_schema: dict[str, Any] = Field(default_factory=dict, alias="schema")
    metadata: dict[str, Any] = Field(default_factory=dict)


class DashboardDatasetRecordsRequest(BaseModel):
    tenant_id: str | None = None
    dataset_id: str
    records: list[dict[str, Any]] = Field(default_factory=list)
    external_key_field: str | None = None


class DashboardDatasetQueryRequest(BaseModel):
    tenant_id: str | None = None
    dataset_id: str
    filters: dict[str, Any] = Field(default_factory=dict)
    search: str | None = None
    sort_by: str | None = None
    sort_order: Literal["asc", "desc"] = "desc"
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)


class DashboardDatasetDeleteRecordsRequest(BaseModel):
    tenant_id: str | None = None
    dataset_id: str
    record_ids: list[str] = Field(default_factory=list)
    external_keys: list[str] = Field(default_factory=list)
