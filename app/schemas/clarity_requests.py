from pydantic import BaseModel, Field


class ClarityConnectRequest(BaseModel):
    tenant_id: str | None = None
    api_token: str = Field(min_length=10)
    project_name: str | None = None


class ClarityRequest(BaseModel):
    tenant_id: str | None = None
    num_of_days: int = Field(default=1, ge=1, le=3)
    dimensions: list[str] = Field(default_factory=list, max_length=3)
    include_raw: bool = False
    row_limit: int = Field(default=20, ge=0, le=100)


class ClarityBehaviorAuditRequest(ClarityRequest):
    focus_url: str | None = None
