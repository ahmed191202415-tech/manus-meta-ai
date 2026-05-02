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


def _storage_probe():
    try:
        import os, requests
        base = (os.getenv('INTELLIGENCE_SUPABASE_URL') or os.getenv('SUPABASE_URL') or '').rstrip('/')
        key = os.getenv('INTELLIGENCE_SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_SERVICE_ROLE_KEY') or ''
        if not base or not key:
            return {'ok': False, 'reason': 'storage env missing'}
        headers = {'apikey': key, 'Authorization': f'Bearer {key}', 'Accept': 'application/json'}
        tables = ['raw_insights_daily','derived_metrics_daily','baselines','analysis_runs','diagnostics_daily','relationship_edges','knowledge_rules']
        out = {}
        for table in tables:
            r = requests.get(f'{base}/rest/v1/{table}', headers=headers, params={'select':'*','limit':'1'}, timeout=15)
            out[table] = {'status': r.status_code, 'ok': r.status_code < 300}
        return {'ok': all(v['ok'] for v in out.values()), 'tables': out}
    except Exception as exc:
        return {'ok': False, 'error_type': type(exc).__name__}


@router.get("/health")
async def health():
    return {
        "ok": True,
        "deploy_marker": DEPLOY_MARKER,
        "meta_api_version": META_API_VERSION,
        "export_dir": str(EXPORT_DIR),
        "connection_probe": _connection_probe(),
        "storage_probe": _storage_probe(),
        "message": "Project structure bootstrap is working"
    }
