from __future__ import annotations

import ast
from typing import Any

from fastapi import HTTPException

from app.core.dashboard_plan import lookup


def resolve_reference(reference: Any, results: dict) -> Any:
    return lookup(results, str(reference or "").removeprefix("nodes."))


def select_value(params: dict, results: dict) -> Any:
    return lookup(resolve_reference(params.get("from"), results), str(params.get("path") or ""))


def build_options(params: dict, results: dict) -> list[dict]:
    source = resolve_reference(params.get("from"), results)
    rows = source.get("data", []) if isinstance(source, dict) else source or []
    if not isinstance(rows, list):
        raise HTTPException(status_code=422, detail="Options source must resolve to a list of rows.")
    label_field = str(params.get("label_field") or "name")
    value_field = str(params.get("value_field") or "id")
    options = []
    for row in rows:
        label = lookup(row, label_field)
        value = lookup(row, value_field)
        if value in (None, ""):
            continue
        options.append({"label": str(label if label not in (None, "") else value), "value": value})
    return options


def _numeric(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _matches(row: dict, expected: dict, *, case_sensitive: bool = False) -> bool:
    for field, wanted in expected.items():
        actual = lookup(row, str(field))
        if case_sensitive:
            if actual != wanted:
                return False
        elif str(actual or "").strip().casefold() != str(wanted or "").strip().casefold():
            return False
    return True


def resolve_metric_value(spec: Any, results: dict) -> tuple[float, bool]:
    """Resolve one metric from a connector result without executable code.

    A metric can be a literal number, a direct ``path`` inside a previous node,
    or an aggregate over ``rows_path`` filtered by an exact declarative match.
    The boolean distinguishes a real zero from a missing/unmapped source.
    """
    direct = _numeric(spec)
    if direct is not None:
        return direct, True
    if not isinstance(spec, dict) or not spec.get("from"):
        return 0.0, False
    source = resolve_reference(spec.get("from"), results)
    if source is None:
        return 0.0, False
    if spec.get("path"):
        value = lookup(source, str(spec["path"]))
        numeric = _numeric(value)
        return (numeric or 0.0), numeric is not None

    rows = lookup(source, str(spec.get("rows_path") or "")) if spec.get("rows_path") else source
    if isinstance(rows, dict):
        rows = rows.get("data") or rows.get("rows") or []
    if not isinstance(rows, list):
        return 0.0, False
    where = spec.get("where") or {}
    matched = [
        row for row in rows
        if isinstance(row, dict) and _matches(row, where, case_sensitive=bool(spec.get("case_sensitive")))
    ]
    if not matched:
        return 0.0, False
    value_field = str(spec.get("value_field") or "value")
    values = [_numeric(lookup(row, value_field)) for row in matched]
    numeric_values = [value for value in values if value is not None]
    if not numeric_values:
        return 0.0, False
    aggregate = str(spec.get("aggregate") or "sum").casefold()
    if aggregate == "first":
        return numeric_values[0], True
    if aggregate == "max":
        return max(numeric_values), True
    if aggregate == "min":
        return min(numeric_values), True
    return sum(numeric_values), True


def build_funnel(params: dict, results: dict) -> dict:
    """Build a source-aware funnel from live connector nodes.

    The transform calculates the standard output contract consumed by every
    dashboard renderer: value, cost, transition, drop-off, optional revenue,
    ROAS, source status, and supporting detail metrics for every ordered stage.
    """
    stage_specs = params.get("stages") or []
    spend, spend_resolved = resolve_metric_value(params.get("spend"), results)
    stages: list[dict] = []
    missing_sources: list[dict] = []
    previous_value: float | None = None
    for position, stage_spec in enumerate(stage_specs, start=1):
        value, resolved = resolve_metric_value(stage_spec.get("value"), results)
        required = stage_spec.get("required", True) is not False
        if required and not resolved:
            missing_sources.append(
                {
                    "stage_id": stage_spec.get("id"),
                    "source": stage_spec.get("source"),
                    "reason": "metric_not_found_in_live_preview",
                }
            )
        transition = None if previous_value in (None, 0) else value / previous_value
        dropoff = None if transition is None else max(0.0, 1.0 - transition)
        revenue, revenue_resolved = resolve_metric_value(stage_spec.get("revenue"), results)
        explicit_roas, roas_resolved = resolve_metric_value(stage_spec.get("roas"), results)
        roas = explicit_roas if roas_resolved else (revenue / spend if revenue_resolved and spend else None)
        detail_rows = []
        for detail in stage_spec.get("details") or []:
            detail_value, detail_resolved = resolve_metric_value(detail.get("value"), results)
            detail_rows.append(
                {
                    "id": detail.get("id"),
                    "label": detail.get("label") or detail.get("id"),
                    "value": detail_value if detail_resolved else None,
                    "source": detail.get("source") or stage_spec.get("source"),
                    "source_status": "live" if detail_resolved else "missing",
                }
            )
        stages.append(
            {
                "id": stage_spec.get("id"),
                "label": stage_spec.get("label") or stage_spec.get("id"),
                "position": position,
                "numeric_value": value if resolved else None,
                "value": value if resolved else None,
                "source": stage_spec.get("source"),
                "source_status": "live" if resolved else "missing",
                "cost": (spend / value) if spend_resolved and value else None,
                "transition_rate": transition,
                "drop_rate": dropoff,
                "revenue": revenue if revenue_resolved else None,
                "roas": roas,
                "details": detail_rows,
            }
        )
        if resolved:
            previous_value = value
    complete = not missing_sources and len(stages) >= 2
    return {
        "status": "ready" if complete else "incomplete",
        "complete": complete,
        "stages": stages,
        "spend": spend if spend_resolved else None,
        "missing_sources": missing_sources,
    }


def flatten_numeric_results(results: dict) -> dict[str, float]:
    values: dict[str, float] = {}
    for node_id, result in results.items():
        if isinstance(result, (int, float)) and not isinstance(result, bool):
            values[node_id] = float(result)
        if isinstance(result, dict):
            for key, value in result.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    values[f"{node_id}_{key}"] = float(value)
    return values


def safe_formula(expression: str, names: dict[str, float]) -> float | None:
    def evaluate(node):
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return float(node.value)
        if isinstance(node, ast.Name) and node.id in names:
            return names[node.id]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = evaluate(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            left = evaluate(node.left)
            right = evaluate(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            return None if right == 0 else left / right
        raise HTTPException(status_code=422, detail="Formula contains an unsupported expression.")

    try:
        return evaluate(ast.parse(expression, mode="eval"))
    except (SyntaxError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid formula: {exc}") from exc
