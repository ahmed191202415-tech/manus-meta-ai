from typing import Dict, Any, Optional, List, Literal
from pydantic import BaseModel, Field


class RawMetaRequest(BaseModel):
    """Dynamic Meta Graph write request for explicit user commands."""

    method: Literal["POST", "DELETE"] = Field(
        description="Meta Graph write method. Use POST for create, update, publish, pause, resume, or reply; DELETE for deletion.",
    )
    path: str = Field(
        min_length=1,
        description="Meta Graph path without domain or API version, for example act_123/campaigns, 456, or 789/feed.",
    )
    params: Dict[str, Any] = Field(default_factory=dict, description="Optional Meta Graph query parameters.")
    data: Dict[str, Any] = Field(default_factory=dict, description="Confirmed Meta Graph write payload.")


class ReadOnlyMetaQueryRequest(BaseModel):
    """Dynamic read-only Meta Graph request for runtime discovery and fetching."""

    path: str = Field(
        min_length=1,
        description=(
            "Meta Graph path without domain or API version. Build it from the user's question. Examples: "
            "me/adaccounts, act_123/campaigns, 456/adsets, 789/ads, 456/insights, or act_123/insights."
        ),
    )
    params: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Focused Meta Graph GET parameters such as fields, date_preset, time_range, level, filtering, "
            "breakdowns, and limit. Ask for a small useful field list first, then expand with another focused query."
        ),
    )


class SmartMetaInsightsRequest(BaseModel):
    account_id: Optional[str] = Field(
        default=None,
        description="Optional Meta ad account ID. Pass act_123 or 123 when known.",
    )
    account_name: Optional[str] = Field(
        default=None,
        description="Optional ad account name such as BeOn. Use when the user names the account instead of its ID.",
    )
    campaign_id: Optional[str] = None
    adset_id: Optional[str] = None
    ad_id: Optional[str] = None
    date_preset: Optional[str] = Field(default="last_7d", description="Meta date preset such as today, yesterday, last_7d, or last_30d.")
    since: Optional[str] = Field(default=None, description="Optional YYYY-MM-DD start date. Use with until instead of date_preset.")
    until: Optional[str] = Field(default=None, description="Optional YYYY-MM-DD end date. Use with since instead of date_preset.")
    level: Optional[Literal["campaign", "adset", "ad"]] = None
    time_increment: Optional[str] = Field(default=None, description="Optional Meta time increment, for example 1 for daily rows.")
    breakdowns: Optional[str] = Field(default=None, description="Optional comma-separated Meta breakdowns.")
    limit: int = Field(default=100, ge=1, le=500)


class CampaignCreateRequest(BaseModel):
    account_id: str
    name: str
    objective: str
    status: str = "PAUSED"
    special_ad_categories: List[str] = Field(default_factory=list)
    buying_type: Optional[str] = None
    is_adset_budget_sharing_enabled: bool = False
    extra_params: Dict[str, Any] = Field(default_factory=dict)


class AdSetCreateRequest(BaseModel):
    account_id: str
    name: str
    campaign_id: str
    optimization_goal: str
    billing_event: str
    status: str = "PAUSED"
    targeting: Dict[str, Any] = Field(default_factory=dict)
    bid_strategy: Optional[str] = None
    daily_budget: Optional[int] = None
    lifetime_budget: Optional[int] = None
    bid_amount: Optional[int] = None
    promoted_object: Optional[Dict[str, Any]] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    attribution_spec: Optional[List[Dict[str, Any]]] = None
    extra_params: Dict[str, Any] = Field(default_factory=dict)


class CreativeCreateRequest(BaseModel):
    account_id: str
    name: str
    object_story_spec: Optional[Dict[str, Any]] = None
    asset_feed_spec: Optional[Dict[str, Any]] = None
    degrees_of_freedom_spec: Optional[Dict[str, Any]] = None
    url_tags: Optional[str] = None
    extra_params: Dict[str, Any] = Field(default_factory=dict)


class AdCreateRequest(BaseModel):
    account_id: str
    name: str
    adset_id: str
    creative: Dict[str, Any]
    status: str = "PAUSED"
    tracking_specs: Optional[List[Dict[str, Any]]] = None
    extra_params: Dict[str, Any] = Field(default_factory=dict)


class CustomAudienceCreateRequest(BaseModel):
    account_id: str
    name: str
    subtype: str = "CUSTOM"
    description: Optional[str] = None
    customer_file_source: Optional[str] = "USER_PROVIDED_ONLY"
    rule: Optional[Dict[str, Any]] = None
    prefill: Optional[bool] = None
    retention_days: Optional[int] = None
    lookalike_spec: Optional[Dict[str, Any]] = None
    pixel_id: Optional[str] = None
    extra_params: Dict[str, Any] = Field(default_factory=dict)


class PixelCreateRequest(BaseModel):
    account_id: str
    name: str
    extra_params: Dict[str, Any] = Field(default_factory=dict)


class AudienceUsersRequest(BaseModel):
    payload: Dict[str, Any] = Field(default_factory=dict)
