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

