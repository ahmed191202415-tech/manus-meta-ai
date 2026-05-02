from fastapi import APIRouter
from app.config import EXPORT_DIR, META_API_VERSION

router = APIRouter(tags=["health"])

DEPLOY_MARKER = "2026-05-02-auth-fallback-5c090af"


def _connection_probe():
    try:
        from app.core.oauth_store import list_tenant_accounts, get_active_meta_connection_for_tenant, is_account_expired
        tenants = list_tenant_accounts(include_deleted=False)
        active_tenants = 0
        connected_tenants = 0
        for account in tenants:
            status = str((account or {}).get("status") or "").lower()
            if status in {"disabled", "deleted"} or is_account_expired(account):
                continue
            active_tenants += 1
            tenant_id = account.get("tenant_id")
            if tenant_id and get_active_meta_connection_for_tenant(tenant_id):
                connected_tenants += 1
        return {"ok": True, "active_tenants": active_tenants, "connected_tenants": connected_tenants}
    except Exception as exc:
        return {"ok": False, "error_type": type(exc).__name__}


@router.get("/health")
async def health():
    return {
        "ok": True,
        "deploy_marker": DEPLOY_MARKER,
        "meta_api_version": META_API_VERSION,
        "export_dir": str(EXPORT_DIR),
        "connection_probe": _connection_probe(),
        "message": "Project structure bootstrap is working"
    }
