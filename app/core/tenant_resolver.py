from fastapi import HTTPException, Request

from app.core.oauth_store import get_latest_google_connection


def resolve_tenant_id_for_google(request: Request, tenant_id: str | None = None) -> str:
    resolved = str(tenant_id or request.session.get("tenant_id") or "").strip()
    if resolved:
        return resolved
    try:
        latest = get_latest_google_connection()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Google connection storage is not available: {exc}") from exc
    if latest and latest.get("tenant_id"):
        return str(latest["tenant_id"]).strip()
    raise HTTPException(status_code=401, detail="Tenant is required for GA4 requests. Connect Google first or pass tenant_id.")
