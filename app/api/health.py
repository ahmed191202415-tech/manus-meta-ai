from fastapi import APIRouter
from app.config import EXPORT_DIR, META_API_VERSION

router = APIRouter(tags=["health"])

DEPLOY_MARKER = "2026-05-02-auth-fallback-5c090af"


def _connection_probe():
    try:
        from app.core.oauth_store import get_latest_meta_connection
        connection = get_latest_meta_connection()
        return {
            "ok": True,
            "has_saved_meta_connection": bool(connection and connection.get("meta_access_token")),
            "tenant_id_present": bool(connection and connection.get("tenant_id")),
            "meta_user_id_present": bool(connection and connection.get("meta_user_id")),
        }
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
