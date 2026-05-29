from pydantic import BaseModel, EmailStr, Field


class TenantRegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    display_name: str | None = None


class TenantLoginRequest(BaseModel):
    email: EmailStr
    password: str


class TenantMetaAppRequest(BaseModel):
    meta_app_id: str
    meta_app_secret: str
    meta_oauth_scopes: str | None = None
    webhook_verify_token: str | None = None
    webhook_callback_url: str | None = None


class TenantPageSelectionRequest(BaseModel):
    page_id: str
    page_name: str | None = None
    page_access_token: str | None = None


class TenantInviteRequest(BaseModel):
    tenant_id: str
    display_name: str | None = None
    email: EmailStr | None = None


class TenantEmailAccessRequest(BaseModel):
    email: EmailStr
    display_name: str | None = None
    subscription_days: int | None = Field(default=None, ge=1, le=3650)


class TenantAccessStatusRequest(BaseModel):
    email: EmailStr
    status: str
    subscription_days: int | None = Field(default=None, ge=1, le=3650)
