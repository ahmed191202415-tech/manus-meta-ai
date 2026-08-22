from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from fastapi import HTTPException, Request

from app.analytics.clarity_metrics import normalize_clarity_export, summarize_clarity_metrics
from app.analytics.ga4_preprocessing import normalize_ga4_report
from app.config import SESSION_SECRET
from app.core.auth import resolve_access_token
from app.core.clarity_client import run_clarity_live_insights_with_fallbacks
from app.core.dashboard_plan import connector_catalog, lookup, resolve_templates, validate_plan
from app.core.dashboard_transforms import build_options, flatten_numeric_results, safe_formula, select_value
from app.core.ga4_client import list_ga4_properties, run_ga4_funnel_report, run_ga4_report
from app.core.meta_client import meta_call, normalize_account_id
from app.schemas.dashboard_runtime_requests import DashboardQueryNode, DashboardQueryPlan


_DEFAULT_FIELDS = {
    "accounts": "id,name,account_id,account_status,currency,timezone_name",
    "campaigns": "id,name,status,effective_status,objective,created_time,updated_time",
    "adsets": "id,name,campaign_id,status,effective_status,optimization_goal,created_time,updated_time",
    "ads": "id,name,adset_id,campaign_id,status,effective_status,created_time,updated_time",
}


async def execute_plan(plan: DashboardQueryPlan, request: Request, inputs: dict | None = None, trigger: str = "manual") -> dict:
    validation = validate_plan(plan)
    if not validation["valid"]:
        raise HTTPException(status_code=422, detail=validation)
    inputs = inputs or {}
    results: dict[str, Any] = {}
    statuses: list[dict] = []
    nodes_by_id = {node.id: node for node in plan.nodes}
    for node_id in validation["execution_order"]:
        node = nodes_by_id[node_id]
        missing_inputs = [key for key in node.required_inputs if lookup(inputs, key) in (None, "")]
        if missing_inputs:
            statuses.append({"node_id": node.id, "status": "waiting_for_input", "missing_inputs": missing_inputs})
            continue
        if node.run_when not in {"always", trigger} and trigger != "always":
            statuses.append({"node_id": node.id, "status": "not_triggered", "run_when": node.run_when})
            continue
        if any(dependency not in results for dependency in node.depends_on):
            statuses.append({"node_id": node.id, "status": "blocked_by_dependency"})
            continue
        params = resolve_templates(node.params, {"inputs": inputs, "nodes": results})
        try:
            result = await _execute_node(node, params, request, results)
            results[node.id] = result
            statuses.append({"node_id": node.id, "status": "success", "connector": node.connector, "operation": node.operation})
        except HTTPException as exc:
            statuses.append({"node_id": node.id, "status": "failed", "error": exc.detail})
            if not node.optional:
                raise HTTPException(
                    status_code=exc.status_code,
                    detail={"message": "Dashboard query plan failed.", "failed_node": node.id, "node_status": statuses, "connector_error": exc.detail},
                ) from exc
        except Exception as exc:
            statuses.append({"node_id": node.id, "status": "failed", "error": str(exc)})
            if not node.optional:
                raise HTTPException(status_code=502, detail={"message": "Dashboard query plan failed.", "failed_node": node.id, "node_status": statuses, "connector_error": str(exc)}) from exc
    output = resolve_templates(plan.output, {"inputs": inputs, "nodes": results}) if plan.output else results
    return {
        "plan_id": plan.id,
        "status": "success" if all(item["status"] in {"success", "not_triggered"} for item in statuses) else "partial",
        "inputs": inputs,
        "data": output,
        "nodes": results,
        "node_status": statuses,
        "executed_at": int(time.time()),
    }


async def _execute_node(node: DashboardQueryNode, params: dict, request: Request, results: dict) -> Any:
    if node.connector == "meta":
        return await _execute_meta(node.operation, params, request)
    if node.connector == "ga4":
        return _execute_ga4(node.operation, params, request)
    if node.connector == "clarity":
        return _execute_clarity(params, request)
    return _execute_transform(node.operation, params, results)


async def _execute_meta(operation: str, params: dict, request: Request) -> dict:
    token = await resolve_access_token(request)
    limit = min(max(int(params.get("limit") or 100), 1), 500)
    if operation == "list_accounts":
        path = "me/adaccounts"
        query = {"fields": params.get("fields") or _DEFAULT_FIELDS["accounts"], "limit": limit}
    elif operation in {"list_campaigns", "list_adsets", "list_ads"}:
        entity = operation.removeprefix("list_")
        account_id = normalize_account_id(str(params.get("account_id") or ""))
        if not account_id:
            raise HTTPException(status_code=422, detail="account_id is required.")
        path = f"{account_id}/{entity}"
        query = {"fields": params.get("fields") or _DEFAULT_FIELDS[entity], "limit": limit}
        if operation == "list_adsets" and params.get("campaign_id"):
            path = f"{params['campaign_id']}/adsets"
        elif operation == "list_ads" and params.get("adset_id"):
            path = f"{params['adset_id']}/ads"
        elif operation == "list_ads" and params.get("campaign_id"):
            path = f"{params['campaign_id']}/ads"
    elif operation == "insights":
        scope_id = str(params.get("scope_id") or "").strip()
        if not scope_id:
            raise HTTPException(status_code=422, detail="scope_id is required.")
        path = f"{scope_id}/insights"
        query = {key: value for key, value in params.items() if key not in {"scope_id"}}
    else:
        path = str(params.get("path") or "").strip().lstrip("/")
        query = dict(params.get("params") or {})
    return meta_call("GET", path, token, params=query)


def _tenant_id(params: dict, request: Request) -> str:
    tenant_id = str(params.get("tenant_id") or request.session.get("tenant_id") or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=422, detail="tenant_id is required for this connector.")
    return tenant_id


def _execute_ga4(operation: str, params: dict, request: Request) -> Any:
    tenant_id = _tenant_id(params, request)
    if operation == "list_properties":
        return {"data": list_ga4_properties(tenant_id)}
    if operation == "funnel":
        return run_ga4_funnel_report(
            tenant_id,
            params.get("property_id"),
            params.get("steps") or [],
            params.get("start_date") or "30daysAgo",
            params.get("end_date") or "today",
        )
    payload = run_ga4_report(
        tenant_id,
        params.get("property_id"),
        params.get("dimensions") or [],
        params.get("metrics") or [],
        params.get("start_date") or "30daysAgo",
        params.get("end_date") or "today",
        limit=params.get("limit") or 100,
        filters=params.get("filters"),
        order_by=params.get("order_by"),
        offset=params.get("offset") or 0,
        metric_aggregations=params.get("metric_aggregations"),
    )
    return {**payload, "normalized_rows": normalize_ga4_report(payload)}


def _execute_clarity(params: dict, request: Request) -> dict:
    tenant_id = _tenant_id(params, request)
    payload = run_clarity_live_insights_with_fallbacks(
        tenant_id,
        params.get("num_of_days") or 1,
        params.get("dimensions") or [],
    )
    rows = normalize_clarity_export(payload)
    return {**payload, "normalized_rows": rows, "summary": summarize_clarity_metrics(rows)}


def _execute_transform(operation: str, params: dict, results: dict) -> Any:
    if operation == "select":
        return select_value(params, results)
    if operation == "options":
        return build_options(params, results)
    return safe_formula(str(params.get("expression") or ""), flatten_numeric_results(results))


def create_confirmation_token(plan: DashboardQueryPlan, preview: dict, ttl_seconds: int = 1800) -> str:
    payload = {
        "plan_hash": _plan_hash(plan),
        "preview_hash": hashlib.sha256(json.dumps(preview.get("data"), sort_keys=True, default=str).encode()).hexdigest(),
        "exp": int(time.time()) + ttl_seconds,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    signature = hmac.new(SESSION_SECRET.encode(), raw, hashlib.sha256).digest()
    return f"{_b64encode(raw)}.{_b64encode(signature)}"


def verify_confirmation_token(token: str, plan: DashboardQueryPlan) -> dict:
    try:
        raw_part, signature_part = token.split(".", 1)
        raw = _b64decode(raw_part)
        signature = _b64decode(signature_part)
        expected = hmac.new(SESSION_SECRET.encode(), raw, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("bad signature")
        payload = json.loads(raw)
        if payload.get("exp", 0) < int(time.time()):
            raise ValueError("expired")
        if payload.get("plan_hash") != _plan_hash(plan):
            raise ValueError("plan changed after preview")
        return payload
    except Exception as exc:
        raise HTTPException(status_code=409, detail=f"Preview confirmation is invalid: {exc}") from exc


def _plan_hash(plan: DashboardQueryPlan) -> str:
    canonical = json.dumps(plan.model_dump(exclude_none=True), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
