from __future__ import annotations

import json
import re
from typing import Any

from app.schemas.dashboard_runtime_requests import DashboardQueryPlan


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
        "funnel": {
            "required": ["stages"],
            "description": "Build an ordered live-data funnel with source, cost, transition, drop-off, revenue, and ROAS fields.",
        },
    },
}

_NODE_REFERENCE = re.compile(r"\{\{\s*nodes\.([A-Za-z0-9_.-]+)")
_LEGACY_INPUT_TEMPLATE = re.compile(r"^\{\s*([A-Za-z0-9_.-]+)\s*\}$")

_LEGACY_RESOURCE_OPERATIONS = {
    "meta": {
        "accounts": "list_accounts",
        "ad_accounts": "list_accounts",
        "campaigns": "list_campaigns",
        "adsets": "list_adsets",
        "ad_sets": "list_adsets",
        "ads": "list_ads",
        "insights": "insights",
        "meta_insights": "insights",
    },
    "ga4": {
        "properties": "list_properties",
        "report": "report",
        "funnel": "funnel",
    },
    "clarity": {
        "insights": "insights",
        "clarity_insights": "insights",
    },
}

_LEGACY_CONTROL_KEYS = {
    "connector",
    "source",
    "resource",
    "operation",
    "node_id",
    "depends_on",
    "required_inputs",
    "run_when",
    "optional",
    "cache_ttl_seconds",
    "title",
    "description",
    "output",
}


def _legacy_template(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _legacy_template(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_legacy_template(item) for item in value]
    if not isinstance(value, str):
        return value
    match = _LEGACY_INPUT_TEMPLATE.fullmatch(value.strip())
    return f"{{{{inputs.{match.group(1)}}}}}" if match else value


def _string_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    values = value if isinstance(value, list) else [value]
    return [str(item).strip() for item in values if str(item).strip()]


def compile_runtime_query(query_id: str, descriptor: dict[str, Any]) -> DashboardQueryPlan | None:
    """Compile a compact ChatGPT query descriptor into a safe runtime plan.

    The dashboard creation API historically accepted concise descriptors such
    as ``{connector: meta, resource: campaigns, account_id: {account_id}}``.
    The universal runtime executes explicit node plans.  Compiling at the
    boundary keeps existing dashboards live while preserving the connector
    allow-list and plan validation.
    """
    if not isinstance(descriptor, dict):
        return None
    if descriptor.get("nodes"):
        return DashboardQueryPlan.model_validate(descriptor)

    connector = str(descriptor.get("connector") or descriptor.get("source") or "").strip().casefold()
    resource = str(descriptor.get("resource") or descriptor.get("operation") or query_id).strip().casefold()
    if connector not in _LEGACY_RESOURCE_OPERATIONS:
        return None
    operation = str(descriptor.get("operation") or _LEGACY_RESOURCE_OPERATIONS[connector].get(resource) or "").strip()
    if operation not in CONNECTOR_OPERATIONS.get(connector, {}):
        return None

    params = {
        key: _legacy_template(value)
        for key, value in descriptor.items()
        if key not in _LEGACY_CONTROL_KEYS
    }
    required_inputs = _string_list(descriptor.get("required_inputs"))
    for key in _string_list(descriptor.get("depends_on")):
        if key not in required_inputs:
            required_inputs.append(key)
    for key in CONNECTOR_OPERATIONS[connector][operation].get("required", []):
        if key not in params and key not in required_inputs:
            required_inputs.append(key)

    # Cascading Meta children must never broaden themselves to the whole ad
    # account when their selected parent is missing.
    if connector == "meta" and operation == "list_adsets" and "campaign_id" not in required_inputs:
        required_inputs.append("campaign_id")
    if connector == "meta" and operation == "list_ads":
        parent_key = "adset_id" if resource in {"ads", "ad"} else "campaign_id"
        if parent_key not in required_inputs:
            required_inputs.append(parent_key)

    raw_node_id = str(descriptor.get("node_id") or resource or query_id)
    node_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw_node_id).strip("_") or "query"
    raw_run_when = str(descriptor.get("run_when") or "always")
    run_when = raw_run_when if raw_run_when in {"on_open", "on_change", "manual", "always"} else "always"
    plan_payload = {
        "id": re.sub(r"[^A-Za-z0-9_.-]+", "_", str(query_id)).strip("_") or "runtime_query",
        "title": descriptor.get("title"),
        "description": descriptor.get("description"),
        "nodes": [
            {
                "id": node_id,
                "connector": connector,
                "operation": operation,
                "params": params,
                "required_inputs": required_inputs,
                "run_when": run_when,
                "optional": bool(descriptor.get("optional", False)),
                "cache_ttl_seconds": int(descriptor.get("cache_ttl_seconds") or 60),
            }
        ],
        "output": descriptor.get("output") or {},
    }
    return DashboardQueryPlan.model_validate(plan_payload)


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
        "output_contracts": {
            "funnel": {
                "required_plan_output": ["stages", "complete", "status"],
                "required_presentation_stage_fields": ["id", "label", "source"],
                "runtime_stage_fields": [
                    "numeric_value",
                    "cost",
                    "transition_rate",
                    "drop_rate",
                    "revenue",
                    "roas",
                    "source_status",
                    "details",
                ],
                "publish_rule": "A signed live preview must contain at least two stages and complete=true.",
            }
        },
    }


def execution_order(plan: DashboardQueryPlan) -> list[str]:
    remaining = {node.id: set(node.depends_on) for node in plan.nodes}
    order: list[str] = []
    while remaining:
        ready = [node_id for node_id, dependencies in remaining.items() if not dependencies]
        if not ready:
            raise ValueError("Query plan contains a dependency cycle.")
        for node_id in ready:
            order.append(node_id)
            remaining.pop(node_id)
            for dependencies in remaining.values():
                dependencies.discard(node_id)
    return order


def _referenced_nodes(value: Any) -> set[str]:
    serialized = json.dumps(value, ensure_ascii=False, default=str)
    return {match.group(1).split(".", 1)[0] for match in _NODE_REFERENCE.finditer(serialized)}


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
        referenced = _referenced_nodes(node.params)
        unknown_references = sorted(referenced - node_ids)
        if unknown_references:
            errors.append({"node_id": node.id, "message": "Node parameters reference unknown nodes.", "missing": unknown_references})
        undeclared_dependencies = sorted(referenced - set(node.depends_on))
        if undeclared_dependencies:
            errors.append({
                "node_id": node.id,
                "message": "Referenced nodes must be declared in depends_on.",
                "missing": undeclared_dependencies,
            })
        if node.connector == "meta" and node.operation == "graph_read":
            path = str(node.params.get("path") or "")
            if path.startswith(("http://", "https://")):
                errors.append({"node_id": node.id, "message": "Meta graph_read accepts Graph paths only."})
        if node.connector == "transform" and node.operation == "funnel":
            stages = node.params.get("stages") or []
            if not isinstance(stages, list) or len(stages) < 2:
                errors.append({"node_id": node.id, "message": "A funnel transform requires at least two ordered stages."})
                continue
            stage_ids = []
            for position, stage in enumerate(stages, start=1):
                if not isinstance(stage, dict):
                    errors.append({"node_id": node.id, "message": f"Funnel stage {position} must be an object."})
                    continue
                missing_stage_fields = [key for key in ("id", "label", "source", "value") if not stage.get(key)]
                if missing_stage_fields:
                    errors.append({
                        "node_id": node.id,
                        "message": f"Funnel stage {position} is incomplete.",
                        "missing": missing_stage_fields,
                    })
                stage_ids.append(stage.get("id"))
            if len(stage_ids) != len(set(stage_ids)):
                errors.append({"node_id": node.id, "message": "Funnel stage IDs must be unique."})
    output_references = _referenced_nodes(plan.output)
    unknown_output_references = sorted(output_references - node_ids)
    if unknown_output_references:
        errors.append({"message": "Plan output references unknown nodes.", "missing": unknown_output_references})
    try:
        order = execution_order(plan)
    except ValueError as exc:
        errors.append({"message": str(exc)})
        order = []
    return {
        "valid": not errors,
        "plan_id": plan.id,
        "node_count": len(plan.nodes),
        "errors": errors,
        "warnings": warnings,
        "execution_order": order,
    }


def lookup(value: Any, path: str) -> Any:
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


def resolve_templates(value: Any, context: dict) -> Any:
    if isinstance(value, dict):
        return {key: resolve_templates(item, context) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_templates(item, context) for item in value]
    if not isinstance(value, str):
        return value
    if value.startswith("{{") and value.endswith("}}") and value.count("{{") == 1:
        return lookup(context, value[2:-2].strip())
    rendered = value
    while "{{" in rendered and "}}" in rendered:
        start = rendered.index("{{")
        end = rendered.index("}}", start)
        path = rendered[start + 2:end].strip()
        resolved = lookup(context, path)
        replacement = "" if resolved is None else str(resolved)
        rendered = rendered[:start] + replacement + rendered[end + 2:]
    return rendered
