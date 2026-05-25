from pydantic import BaseModel, Field


class GA4PropertySelectionRequest(BaseModel):
    tenant_id: str | None = None
    property_id: str = Field(min_length=1)
    property_name: str | None = None


class GA4PropertyListRequest(BaseModel):
    tenant_id: str | None = None
