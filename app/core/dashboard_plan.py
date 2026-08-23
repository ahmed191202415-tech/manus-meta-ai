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
