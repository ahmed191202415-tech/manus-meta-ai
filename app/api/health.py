from fastapi import APIRouter
from app.config import EXPORT_DIR, META_API_VERSION

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    return {
        "ok": True,
        "meta_api_version": META_API_VERSION,
        "export_dir": str(EXPORT_DIR),
        "message": "Project structure bootstrap is working"
    }


@router.get("/health/auth_connection_probe")
async def auth_connection_probe():
    """Safe auth diagnostics. Does not expose tokens."""
    out = {"ok": False, "steps": []}
    try:
        from app.core.oauth_store import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, get_latest_meta_connection, list_tenant_accounts
        out["supabase_url_set"] = bool(SUPABASE_URL)
        out["service_role_set"] = bool(SUPABASE_SERVICE_ROLE_KEY)
        try:
            tenants = list_tenant_accounts(include_deleted=False)
            out["tenant_count"] = len(tenants or [])
        except Exception as exc:
            out["tenant_error"] = {"type": type(exc).__name__, "message": str(exc)[:500]}
        try:
            conn = get_latest_meta_connection()
            out["has_latest_connection"] = bool(conn)
            if conn:
                out["latest_connection"] = {
                    "tenant_id": conn.get("tenant_id"),
                    "meta_user_id": conn.get("meta_user_id"),
                    "meta_user_name": conn.get("meta_user_name"),
                    "updated_at": conn.get("updated_at"),
                    "has_token": bool(conn.get("meta_access_token")),
                }
        except Exception as exc:
            out["connection_error"] = {"type": type(exc).__name__, "message": str(exc)[:500]}
        out["ok"] = bool(out.get("has_latest_connection"))
        return out
    except Exception as exc:
        out["fatal"] = {"type": type(exc).__name__, "message": str(exc)[:500]}
        return out
