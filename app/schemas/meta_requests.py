from typing import Dict, Any, Optional, List, Literal
from pydantic import BaseModel, Field


class RawMetaRequest(BaseModel):
    method: Literal["GET", "POST", "DELETE"] = "GET"
    path: str
    params: Dict[str, Any] = Field(default_factory=dict)
    data: Dict[str, Any] = Field(default_factory=dict)


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