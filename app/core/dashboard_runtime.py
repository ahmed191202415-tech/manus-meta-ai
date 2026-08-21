from __future__ import annotations

import ast
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
from app.core.ga4_client import list_ga4_properties, run_ga4_funnel_report, run_ga4_report
from app.core.meta_client import meta_call, normalize_account_id
from app.schemas.dashboard_runtime_requests import DashboardQueryNode, DashboardQueryPlan


CONNECTOR_OPERATIONS = {
    "meta": {
        "list_accounts": {"required": [], "description": "List available Meta ad accounts."},
        "list_campaigns": {"required": ["account_id"], "description": "List campaigns for an ad account."},
        "list_adsets": {"required": ["account_id"], "description": "List ad sets, optionally filtered by campaign_id."},
        "list_ads": {"required": ["account_id"], "description": "List ads, optionally filtered by adset_id or campaign_id."},
        "insights": {"required": ["scope_id"], "description": "Read insights for an account, campaign, ad set, or ad."},
        "graph_read": {"required": ["path"], "description": "Read any safe Meta Graph path."},
    },
    "ga4": {
        "list_properties": {"required": ["tenant_id"], "description": "List connected GA4 properties."},
        "report": {"required": ["tenant_id", "metrics"], "description": "Run an arbitrary GA4 report."},
        "funnel": {"required": ["tenant_id", "steps"], "description": "Run a GA4 funnel report."},
    },
    "clarity": {
        "insights": {"required": ["tenant_id"], "description": "Read Clarity live insights."},
    },
    "transform": {
        "select": {"required": ["from", "path"], "description": "Select a nested value from a previous node."},
        "formula": {"required": ["expression"], "description": "Calculate a numeric expression from prior results."},
        "options": {"required": ["from"], "description": "Convert rows into label/value dropdown options."},
    },
}

_DEFAULT_FIELDS = {
    "accounts": "id,name,account_id,account_status,currency,timezone_name",
    "campaigns": "id,name,status,effective_status,objective,created_time,updated_time",
    "adsets": "id,name,campaign_id,status,effective_status,optimization_goal,created_time,updated_time",
    "ads": "id,name,adset_id,campaign_id,status,effective_status,created_time,updated_time",
}


def connector_catalog() -> dict:
    return {
        "connectors": [
            {
                "id": connector,
                "operations": [
                    {"id": operation, **metadata}
                    for operation, metadata in operations.items()
                ],
            }
            for connector, operations in CONNECTOR_OPERATIONS.items()
        ],
        "template_syntax": "{{inputs.key}} or {{nodes.node_id.path}}",
        "workflow": ["validate", "preview", "user_confirmation", "publish"],
    }


def validate_plan(plan: DashboardQueryPlan) -> dict:
    errors: list[dict] = []
    warnings: list[dict] = []
    node_ids = {node.id for node in plan.nodes}
    for node in plan.nodes:
        operations = CONNECTOR_OPERATIONS.get(node.connector, {})
        if node.operation not in operations:
            errors.append({"node_id": node.id, "message": f"Unsupported operation: {node.connector}.{node.operation}"})
            continue
        missing_declared = [
            key for key in operations[node.operation].get("required", [])
            if key not in node.params and key not in node.required_inputs
        ]
        if missing_declared:
            errors.append({"node_id": node.id, "message": "Required parameters are missing.", "missing": missing_declared})
        for dependency in node.depends_on:
            if dependency not in node_ids:
                errors.append({"node_id": node.id, "message": f"Unknown dependency: {dependency}"})
        if node.connector == "meta" and node.operation == "graph_read":
            path = str(node.params.get("path") or "")
            if path.startswith(("http://", "https://")):
                errors.append({"node_id": node.id, "message": "Meta graph_read accepts Graph paths only."})
        if not node.depends_on and "{{nodes." in json.dumps(node.params):
            warnings.append({"node_id": node.id, "message": "The node references prior results but has no depends_on declaration."})
    try:
        execution_order = _execution_order(plan)
    except ValueError as exc:
        errors.append({"message": str(exc)})
        execution_order = []
    return {
        "valid": not errors,
        "plan_id": plan.id,
        "node_count": len(plan.nodes),
        "errors": errors,
        "warnings": warnings,
        "execution_order": execution_order,
    }


async def execute_plan(plan: DashboardQueryPlan, request: Request, inputs: dict | None = None, trigger: str = "manual") -> dict:
    validation = validate_plan(plan)
    if not validation["valid"]:
        raise HTTPException(status_code=422, detail=validation)
    inputs = inputs or {}
    results: dict[str, Any] = {}
    statuses: list[dict] = []
    for node_id in validation["execution_order"]:
        node = next(item for item in plan.nodes if item.id == node_id)
        missing_inputs = [key for key in node.required_inputs if _lookup(inputs, key) in (None, "")]
        if missing_inputs:
            statuses.append({"node_id": node.id, "status": "waiting_for_input", "missing_inputs": missing_inputs})
            continue
        if node.run_when not in {"always", trigger} and trigger != "always":
            statuses.append({"node_id": node.id, "status": "not_triggered", "run_when": node.run_when})
            continue
        if any(dependency not in results for dependency in node.depends_on):
            statuses.append({"node_id": node.id, "status": "blocked_by_dependency"})
            continue
        params = _resolve_templates(node.params, {"inputs": inputs, "nodes": results})
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
    output = _resolve_templates(plan.output, {"inputs": inputs, "nodes": results}) if plan.output else results
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
        source = _resolve_reference(params.get("from"), results)
        return _lookup(source, str(params.get("path") or ""))
    if operation == "options":
        source = _resolve_reference(params.get("from"), results)
        rows = source.get("data", []) if isinstance(source, dict) else source or []
        label_field = str(params.get("label_field") or "name")
        value_field = str(params.get("value_field") or "id")
        return [{"label": _lookup(row, label_field), "value": _lookup(row, value_field)} for row in rows]
    names = _flatten_numeric_results(results)
    return _safe_formula(str(params.get("expression") or ""), names)


def _execution_order(plan: DashboardQueryPlan) -> list[str]:
    remaining = {node.id: set(node.depends_on) for node in plan.nodes}
    order: list[str] = []
    while remaining:
        ready = [node_id for node_id, deps in remaining.items() if not deps]
        if not ready:
            raise ValueError("Query plan contains a dependency cycle.")
        for node_id in ready:
            order.append(node_id)
            remaining.pop(node_id)
            for deps in remaining.values():
                deps.discard(node_id)
    return order


def _resolve_templates(value: Any, context: dict) -> Any:
    if isinstance(value, dict):
        return {key: _resolve_templates(item, context) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_templates(item, context) for item in value]
    if not isinstance(value, str):
        return value
    if value.startswith("{{") and value.endswith("}}") and value.count("{{") == 1:
        return _lookup(context, value[2:-2].strip())
    rendered = value
    while "{{" in rendered and "}}" in rendered:
        start = rendered.index("{{")
        end = rendered.index("}}", start)
        path = rendered[start + 2:end].strip()
        rendered = rendered[:start] + str(_lookup(context, path) or "") + rendered[end + 2:]
    return rendered


def _lookup(value: Any, path: str) -> Any:
    current = value
    for part in [item for item in str(path or "").split(".") if item]:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            current = current[index] if index < len(current) else None
        else:
            return None
    return current


def _resolve_reference(reference: Any, results: dict) -> Any:
    text = str(reference or "")
    return _lookup(results, text.removeprefix("nodes."))


def _flatten_numeric_results(results: dict) -> dict[str, float]:
    values: dict[str, float] = {}
    for node_id, result in results.items():
        if isinstance(result, (int, float)):
            values[node_id] = float(result)
        if isinstance(result, dict):
            for key, value in result.items():
                if isinstance(value, (int, float)):
                    values[f"{node_id}_{key}"] = float(value)
    return values


_FORMULA_OPS = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b if b else None}


def _safe_formula(expression: str, names: dict[str, float]) -> float | None:
    def evaluate(node):
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.Name) and node.id in names:
            return names[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in _FORMULA_OPS:
            return _FORMULA_OPS[type(node.op)](evaluate(node.left), evaluate(node.right))
        raise HTTPException(status_code=422, detail="Formula contains an unsupported expression.")
    try:
        return evaluate(ast.parse(expression, mode="eval"))
    except (SyntaxError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid formula: {exc}") from exc


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
