from fastapi import APIRouter, Query, Request

from app.analytics.clarity_metrics import normalize_clarity_export, summarize_clarity_metrics, top_clarity_entities
from app.analytics.clarity_signals import build_clarity_signals
from app.core.clarity_client import run_clarity_live_insights, run_clarity_live_insights_with_fallbacks
from app.core.oauth_store import get_latest_clarity_connection, purge_clarity_connection, save_clarity_connection
from app.schemas.clarity_requests import ClarityBehaviorAuditRequest, ClarityConnectRequest, ClarityRequest

router = APIRouter(prefix="/clarity", tags=["clarity"])


@router.post("/connect_token")
async def clarity_connect_token(body: ClarityConnectRequest, request: Request):
    tenant_id = _resolve_required_tenant(request, body.tenant_id)
    connection = save_clarity_connection(tenant_id, body.api_token, body.project_name)
    return {"success": True, "tenant_id": tenant_id, "project_name": connection.get("project_name"), "connected": True}


@router.post("/disconnect")
async def clarity_disconnect(request: Request, tenant_id: str | None = Query(default=None)):
    resolved_tenant_id = _resolve_required_tenant(request, tenant_id)
    purge_clarity_connection(resolved_tenant_id)
    return {"success": True, "tenant_id": resolved_tenant_id}


@router.post("/summary")
async def clarity_summary(body: ClarityRequest, request: Request):
    tenant_id = _resolve_optional_tenant(request, body.tenant_id)
    payload = run_clarity_live_insights_with_fallbacks(tenant_id, body.num_of_days, body.dimensions)
    rows = normalize_clarity_export(payload)
    return {**payload, "rows": rows, "summary_metrics": summarize_clarity_metrics(rows)}


@router.post("/pages")
async def clarity_pages(body: ClarityRequest, request: Request):
    tenant_id = _resolve_optional_tenant(request, body.tenant_id)
    payload = run_clarity_live_insights(tenant_id, body.num_of_days, ["URL"])
    rows = normalize_clarity_export(payload)
    return {**payload, "rows": rows, "top_pages": top_clarity_entities(rows, "URL")}


@router.post("/behavior_audit")
async def clarity_behavior_audit(body: ClarityBehaviorAuditRequest, request: Request):
    tenant_id = _resolve_optional_tenant(request, body.tenant_id)
    dimensions = body.dimensions or ["URL", "Device"]
    payload = run_clarity_live_insights_with_fallbacks(tenant_id, body.num_of_days, dimensions)
    rows = normalize_clarity_export(payload)
    if body.focus_url:
        rows = [row for row in rows if body.focus_url in str(row.get("URL") or "")]
    summary = summarize_clarity_metrics(rows)
    return {
        **payload,
        "focus_url": body.focus_url,
        "rows": rows,
        "summary_metrics": summary,
        "signals": build_clarity_signals(summary, rows),
        "top_pages": top_clarity_entities(rows, "URL"),
    }


def _resolve_optional_tenant(request: Request, tenant_id: str | None = None) -> str | None:
    resolved = str(tenant_id or request.session.get("tenant_id") or "").strip()
    if resolved:
        return resolved
    latest = get_latest_clarity_connection()
    return str((latest or {}).get("tenant_id") or "").strip() or None


def _resolve_required_tenant(request: Request, tenant_id: str | None = None) -> str:
    resolved = _resolve_optional_tenant(request, tenant_id)
    if not resolved:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Tenant is required before connecting Clarity.")
    return resolved
