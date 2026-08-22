from __future__ import annotations

import re

from fastapi import HTTPException


SAFE_GA4_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
STRING_FILTER_MATCH_TYPES = {
    "exact": "EXACT",
    "begins_with": "BEGINS_WITH",
    "ends_with": "ENDS_WITH",
    "contains": "CONTAINS",
    "full_regexp": "FULL_REGEXP",
    "partial_regexp": "PARTIAL_REGEXP",
}
NUMERIC_FILTER_OPERATIONS = {
    "equal": "EQUAL",
    "less_than": "LESS_THAN",
    "less_than_or_equal": "LESS_THAN_OR_EQUAL",
    "greater_than": "GREATER_THAN",
    "greater_than_or_equal": "GREATER_THAN_OR_EQUAL",
}
DIMENSION_ORDER_TYPES = {
    "alphanumeric": "ALPHANUMERIC",
    "case_insensitive_alphanumeric": "CASE_INSENSITIVE_ALPHANUMERIC",
    "numeric": "NUMERIC",
}


def dimension(name: str) -> dict:
    return {"name": _safe_ga4_name(name, "dimension")}


def metric(name: str) -> dict:
    return {"name": _safe_ga4_name(name, "metric")}


def date_range(start_date: str, end_date: str) -> dict:
    return {"startDate": start_date, "endDate": end_date}


def _safe_ga4_name(value: str, label: str) -> str:
    clean_value = str(value or "").strip()
    if not SAFE_GA4_NAME.fullmatch(clean_value):
        raise HTTPException(status_code=400, detail=f"Invalid GA4 {label}: {clean_value}")
    return clean_value


def _string_filter_expression(field_name: str, value: str, operator: str = "contains", case_sensitive: bool = False) -> dict:
    clean_value = str(value or "").strip()
    clean_operator = str(operator or "contains").strip().lower()
    if not clean_value:
        raise HTTPException(status_code=400, detail="GA4 string filter value is required.")
    if clean_operator not in STRING_FILTER_MATCH_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported GA4 string filter operator: {clean_operator}")
    return {
        "filter": {
            "fieldName": _safe_ga4_name(field_name, "filter dimension"),
            "stringFilter": {
                "matchType": STRING_FILTER_MATCH_TYPES[clean_operator],
                "value": clean_value,
                "caseSensitive": bool(case_sensitive),
            },
        }
    }


def _maybe_exclude(expression: dict, exclude: bool = False) -> dict:
    return {"notExpression": expression} if exclude else expression


def _in_list_filter_expression(field_name: str, values: list[str], case_sensitive: bool = False) -> dict:
    clean_values = [str(value).strip() for value in (values or []) if str(value).strip()]
    if not clean_values:
        raise HTTPException(status_code=400, detail="GA4 in-list filter values are required.")
    return {
        "filter": {
            "fieldName": _safe_ga4_name(field_name, "filter dimension"),
            "inListFilter": {"values": clean_values, "caseSensitive": bool(case_sensitive)},
        }
    }


def _numeric_value(value) -> dict:
    try:
        return {"doubleValue": float(value)}
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid GA4 numeric filter value: {value}") from exc


def _numeric_filter_expression(field_name: str, value, operator: str = "equal") -> dict:
    clean_operator = str(operator or "equal").strip().lower()
    if clean_operator not in NUMERIC_FILTER_OPERATIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported GA4 numeric filter operator: {clean_operator}")
    return {
        "filter": {
            "fieldName": _safe_ga4_name(field_name, "filter metric"),
            "numericFilter": {
                "operation": NUMERIC_FILTER_OPERATIONS[clean_operator],
                "value": _numeric_value(value),
            },
        }
    }


def _between_filter_expression(field_name: str, from_value, to_value) -> dict:
    return {
        "filter": {
            "fieldName": _safe_ga4_name(field_name, "filter metric"),
            "betweenFilter": {
                "fromValue": _numeric_value(from_value),
                "toValue": _numeric_value(to_value),
            },
        }
    }


def _empty_filter_expression(field_name: str) -> dict:
    return {"filter": {"fieldName": _safe_ga4_name(field_name, "filter dimension"), "emptyFilter": {}}}


def _combine_expressions(expressions: list[dict]) -> dict | None:
    if len(expressions) == 1:
        return expressions[0]
    return {"andGroup": {"expressions": expressions}} if expressions else None


def normalize_ga4_filters(filters: dict | None) -> dict:
    clean_filters = filters or {}
    result = {}
    dimension_expressions = []
    if clean_filters.get("dimensionFilter"):
        dimension_expressions.append(clean_filters["dimensionFilter"])
    if clean_filters.get("page_path_contains"):
        dimension_expressions.append(_string_filter_expression("pagePathPlusQueryString", clean_filters["page_path_contains"]))
    for item in clean_filters.get("dimension_string_filters") or []:
        dimension_expressions.append(_maybe_exclude(_string_filter_expression(
            item.get("dimension"), item.get("value"), item.get("operator", "contains"), item.get("case_sensitive", False)
        ), item.get("exclude", False)))
    for item in clean_filters.get("dimension_in_list_filters") or []:
        dimension_expressions.append(_maybe_exclude(_in_list_filter_expression(
            item.get("dimension"), item.get("values"), item.get("case_sensitive", False)
        ), item.get("exclude", False)))
    for item in clean_filters.get("dimension_empty_filters") or []:
        dimension_expressions.append(_maybe_exclude(_empty_filter_expression(item.get("dimension")), item.get("exclude", False)))
    combined_dimensions = _combine_expressions(dimension_expressions)
    if combined_dimensions:
        result["dimensionFilter"] = combined_dimensions

    metric_expressions = []
    if clean_filters.get("metricFilter"):
        metric_expressions.append(clean_filters["metricFilter"])
    for item in clean_filters.get("metric_numeric_filters") or []:
        metric_expressions.append(_maybe_exclude(_numeric_filter_expression(
            item.get("metric"), item.get("value"), item.get("operator", "equal")
        ), item.get("exclude", False)))
    for item in clean_filters.get("metric_between_filters") or []:
        metric_expressions.append(_maybe_exclude(_between_filter_expression(
            item.get("metric"), item.get("from"), item.get("to")
        ), item.get("exclude", False)))
    combined_metrics = _combine_expressions(metric_expressions)
    if combined_metrics:
        result["metricFilter"] = combined_metrics
    return result


def normalize_ga4_order_bys(order_by: list[dict] | None) -> list[dict]:
    normalized = []
    for item in order_by or []:
        if "metric" in item or "dimension" in item or "pivot" in item:
            normalized.append(item)
            continue
        order_type = str(item.get("type") or "metric").strip().lower()
        name = _safe_ga4_name(item.get("name"), "order-by field")
        result = {"desc": bool(item.get("descending", item.get("desc", False)))}
        if order_type == "metric":
            result["metric"] = {"metricName": name}
        elif order_type == "dimension":
            dimension_order_type = str(item.get("order_type") or "alphanumeric").strip().lower()
            if dimension_order_type not in DIMENSION_ORDER_TYPES:
                raise HTTPException(status_code=400, detail=f"Unsupported GA4 dimension order type: {dimension_order_type}")
            result["dimension"] = {"dimensionName": name, "orderType": DIMENSION_ORDER_TYPES[dimension_order_type]}
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported GA4 order-by type: {order_type}")
        normalized.append(result)
    return normalized


def build_report_request(
    dimensions: list[str], metrics: list[str], start_date: str, end_date: str,
    limit: int, offset: int, filters: dict | None, order_by: list[dict] | None,
    metric_aggregations: list[str] | None,
) -> dict:
    if not metrics:
        raise HTTPException(status_code=400, detail="At least one GA4 metric is required.")
    body = {
        "dateRanges": [date_range(start_date, end_date)],
        "dimensions": [dimension(item) for item in dimensions],
        "metrics": [metric(item) for item in metrics],
        "limit": str(min(max(int(limit or 100), 1), 1000)),
        "offset": str(max(int(offset or 0), 0)),
    }
    body.update(normalize_ga4_filters(filters))
    normalized_order = normalize_ga4_order_bys(order_by)
    if normalized_order:
        body["orderBys"] = normalized_order
    if metric_aggregations:
        body["metricAggregations"] = metric_aggregations
    return body


def build_funnel_request(steps: list[dict], start_date: str, end_date: str) -> dict:
    if not steps:
        raise HTTPException(status_code=400, detail="At least one funnel step is required.")
    normalized_steps = []
    for index, step in enumerate(steps, start=1):
        name = str(step.get("name") or "").strip()
        event_name = str(step.get("event_name") or "").strip()
        if not name or not event_name:
            raise HTTPException(status_code=400, detail=f"Funnel step {index} requires name and event_name.")
        normalized_steps.append({
            "name": name,
            "filterExpression": {"funnelEventFilter": {"eventName": event_name}},
        })
    return {"dateRanges": [date_range(start_date, end_date)], "funnel": {"steps": normalized_steps}}

