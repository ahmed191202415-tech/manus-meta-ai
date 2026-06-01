from datetime import datetime, timedelta, timezone
import re

import requests
from fastapi import HTTPException

from app.core.google_oauth import get_google_service_account_token, refresh_google_access_token
from app.core.oauth_store import (
    get_active_google_connection_for_tenant,
    update_google_tokens,
)

GA4_ADMIN_ACCOUNT_SUMMARIES_URL = "https://analyticsadmin.googleapis.com/v1beta/accountSummaries"
GA4_DATA_BASE_URL = "https://analyticsdata.googleapis.com/v1beta"
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


def _parse_dt(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_expiring(expires_at: str | None) -> bool:
    parsed = _parse_dt(expires_at)
    if not parsed:
        return False
    return parsed <= datetime.now(timezone.utc) + timedelta(minutes=5)


def get_google_connection_or_401(tenant_id: str) -> dict:
    try:
        connection = get_active_google_connection_for_tenant(tenant_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Google connection storage is not available: {exc}") from exc
    if not connection:
        raise HTTPException(status_code=401, detail="Google is not connected for this tenant.")
    return connection


def get_google_credentials_for_tenant(tenant_id: str) -> dict:
    connection = get_google_connection_or_401(tenant_id)
    if connection.get("connection_mode") == "service_account":
        refreshed = get_google_service_account_token()
        updated = update_google_tokens(tenant_id, refreshed)
        return {**connection, **refreshed, **(updated or {})}
    if _is_expiring(connection.get("expires_at")):
        refreshed = refresh_google_access_token(connection.get("refresh_token") or "")
        updated = update_google_tokens(tenant_id, refreshed)
        if updated:
            connection = {**connection, **updated}
        else:
            connection = {**connection, **refreshed}
    return connection


def _auth_headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}


def resolve_ga4_property_id(tenant_id: str, property_id: str | None = None) -> str:
    if property_id:
        return str(property_id).replace("properties/", "").strip()
    connection = get_google_connection_or_401(tenant_id)
    selected = str(connection.get("selected_ga4_property_id") or "").replace("properties/", "").strip()
    if not selected:
        raise HTTPException(status_code=400, detail="GA4 property not selected. Pass property_id or select a property first.")
    return selected


def list_ga4_properties(tenant_id: str) -> list[dict]:
    credentials = get_google_credentials_for_tenant(tenant_id)
    response = requests.get(
        GA4_ADMIN_ACCOUNT_SUMMARIES_URL,
        headers=_auth_headers(credentials["access_token"]),
        timeout=30,
    )
    data = response.json()
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail={"message": "Could not list GA4 properties.", "google_response": data})

    properties = []
    for account in data.get("accountSummaries", []):
        account_name = account.get("displayName")
        account_resource = account.get("account")
        for prop in account.get("propertySummaries", []):
            resource_name = prop.get("property") or ""
            property_id = resource_name.split("/")[-1] if "/" in resource_name else resource_name
            properties.append(
                {
                    "account": account_resource,
                    "account_name": account_name,
                    "property": resource_name,
                    "property_id": property_id,
                    "property_name": prop.get("displayName"),
                    "property_type": prop.get("propertyType"),
                    "parent": prop.get("parent"),
                }
            )
    return properties


def _dimension(name: str) -> dict:
    return {"name": name}


def _metric(name: str) -> dict:
    return {"name": name}


def _date_range(start_date: str, end_date: str) -> dict:
    return {"startDate": start_date, "endDate": end_date}


def _string_filter_expression(field_name: str, value: str, operator: str = "contains", case_sensitive: bool = False) -> dict:
    clean_field_name = str(field_name or "").strip()
    clean_value = str(value or "").strip()
    clean_operator = str(operator or "contains").strip().lower()
    if not SAFE_GA4_NAME.match(clean_field_name):
        raise HTTPException(status_code=400, detail=f"Invalid GA4 filter dimension: {clean_field_name}")
    if not clean_value:
        raise HTTPException(status_code=400, detail="GA4 string filter value is required.")
    if clean_operator not in STRING_FILTER_MATCH_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported GA4 string filter operator: {clean_operator}")
    return {
        "filter": {
            "fieldName": clean_field_name,
            "stringFilter": {
                "matchType": STRING_FILTER_MATCH_TYPES[clean_operator],
                "value": clean_value,
                "caseSensitive": bool(case_sensitive),
            },
        }
    }


def _safe_ga4_name(value: str, label: str) -> str:
    clean_value = str(value or "").strip()
    if not SAFE_GA4_NAME.match(clean_value):
        raise HTTPException(status_code=400, detail=f"Invalid GA4 {label}: {clean_value}")
    return clean_value


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
    if expressions:
        return {"andGroup": {"expressions": expressions}}
    return None


def normalize_ga4_filters(filters: dict | None) -> dict:
    clean_filters = filters or {}
    result = {}
    dimension_expressions = []
    if clean_filters.get("dimensionFilter"):
        dimension_expressions.append(clean_filters["dimensionFilter"])
    if clean_filters.get("page_path_contains"):
        dimension_expressions.append(
            _string_filter_expression("pagePathPlusQueryString", clean_filters["page_path_contains"])
        )
    for item in clean_filters.get("dimension_string_filters") or []:
        dimension_expressions.append(
            _maybe_exclude(
                _string_filter_expression(
                    item.get("dimension"),
                    item.get("value"),
                    item.get("operator", "contains"),
                    item.get("case_sensitive", False),
                ),
                item.get("exclude", False),
            )
        )
    for item in clean_filters.get("dimension_in_list_filters") or []:
        dimension_expressions.append(
            _maybe_exclude(
                _in_list_filter_expression(
                    item.get("dimension"),
                    item.get("values"),
                    item.get("case_sensitive", False),
                ),
                item.get("exclude", False),
            )
        )
    for item in clean_filters.get("dimension_empty_filters") or []:
        dimension_expressions.append(
            _maybe_exclude(_empty_filter_expression(item.get("dimension")), item.get("exclude", False))
        )
    combined_dimensions = _combine_expressions(dimension_expressions)
    if combined_dimensions:
        result["dimensionFilter"] = combined_dimensions
    metric_expressions = []
    if clean_filters.get("metricFilter"):
        metric_expressions.append(clean_filters["metricFilter"])
    for item in clean_filters.get("metric_numeric_filters") or []:
        metric_expressions.append(
            _maybe_exclude(
                _numeric_filter_expression(item.get("metric"), item.get("value"), item.get("operator", "equal")),
                item.get("exclude", False),
            )
        )
    for item in clean_filters.get("metric_between_filters") or []:
        metric_expressions.append(
            _maybe_exclude(
                _between_filter_expression(item.get("metric"), item.get("from"), item.get("to")),
                item.get("exclude", False),
            )
        )
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
            result["dimension"] = {
                "dimensionName": name,
                "orderType": DIMENSION_ORDER_TYPES[dimension_order_type],
            }
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported GA4 order-by type: {order_type}")
        normalized.append(result)
    return normalized


def run_ga4_report(
    tenant_id: str,
    property_id: str | None,
    dimensions: list[str],
    metrics: list[str],
    start_date: str = "30daysAgo",
    end_date: str = "today",
    limit: int = 100,
    filters: dict | None = None,
    order_by: list[dict] | None = None,
    offset: int = 0,
    metric_aggregations: list[str] | None = None,
) -> dict:
    resolved_property_id = resolve_ga4_property_id(tenant_id, property_id)
    credentials = get_google_credentials_for_tenant(tenant_id)
    body = {
        "dateRanges": [_date_range(start_date, end_date)],
        "dimensions": [_dimension(item) for item in dimensions],
        "metrics": [_metric(item) for item in metrics],
        "limit": str(min(max(int(limit or 100), 1), 1000)),
        "offset": str(max(int(offset or 0), 0)),
    }
    normalized_filters = normalize_ga4_filters(filters)
    if normalized_filters.get("dimensionFilter"):
        body["dimensionFilter"] = normalized_filters["dimensionFilter"]
    if normalized_filters.get("metricFilter"):
        body["metricFilter"] = normalized_filters["metricFilter"]
    normalized_order_bys = normalize_ga4_order_bys(order_by)
    if normalized_order_bys:
        body["orderBys"] = normalized_order_bys
    if metric_aggregations:
        body["metricAggregations"] = metric_aggregations
    response = requests.post(
        f"{GA4_DATA_BASE_URL}/properties/{resolved_property_id}:runReport",
        headers=_auth_headers(credentials["access_token"]),
        json=body,
        timeout=45,
    )
    data = response.json()
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail={"message": "GA4 report failed.", "google_response": data})
    data["property_id"] = resolved_property_id
    data["date_range"] = {"start_date": start_date, "end_date": end_date}
    return data


def run_ga4_funnel_report(
    tenant_id: str,
    property_id: str | None,
    steps: list[dict],
    start_date: str = "30daysAgo",
    end_date: str = "today",
) -> dict:
    if not steps:
        raise HTTPException(status_code=400, detail="At least one funnel step is required.")
    resolved_property_id = resolve_ga4_property_id(tenant_id, property_id)
    credentials = get_google_credentials_for_tenant(tenant_id)
    body = {
        "dateRanges": [_date_range(start_date, end_date)],
        "funnel": {
            "steps": [
                {
                    "name": step["name"],
                    "filterExpression": {
                        "funnelEventFilter": {
                            "eventName": step["event_name"],
                        }
                    },
                }
                for step in steps
            ]
        },
    }
    response = requests.post(
        f"https://analyticsdata.googleapis.com/v1alpha/properties/{resolved_property_id}:runFunnelReport",
        headers=_auth_headers(credentials["access_token"]),
        json=body,
        timeout=45,
    )
    data = response.json()
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail={"message": "GA4 funnel report failed.", "google_response": data})
    data["property_id"] = resolved_property_id
    return data


def run_ga4_realtime_report(
    tenant_id: str,
    property_id: str | None,
    dimensions: list[str] | None = None,
    metrics: list[str] | None = None,
    limit: int = 100,
) -> dict:
    resolved_property_id = resolve_ga4_property_id(tenant_id, property_id)
    credentials = get_google_credentials_for_tenant(tenant_id)
    body = {
        "dimensions": [_dimension(item) for item in (dimensions or ["country", "deviceCategory"])],
        "metrics": [_metric(item) for item in (metrics or ["activeUsers"])],
        "limit": str(min(max(int(limit or 100), 1), 1000)),
    }
    response = requests.post(
        f"{GA4_DATA_BASE_URL}/properties/{resolved_property_id}:runRealtimeReport",
        headers=_auth_headers(credentials["access_token"]),
        json=body,
        timeout=45,
    )
    data = response.json()
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail={"message": "GA4 realtime report failed.", "google_response": data})
    data["property_id"] = resolved_property_id
    return data


def get_ga4_metadata(tenant_id: str, property_id: str | None = None) -> dict:
    resolved_property_id = resolve_ga4_property_id(tenant_id, property_id)
    credentials = get_google_credentials_for_tenant(tenant_id)
    response = requests.get(
        f"{GA4_DATA_BASE_URL}/properties/{resolved_property_id}/metadata",
        headers=_auth_headers(credentials["access_token"]),
        timeout=45,
    )
    data = response.json()
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail={"message": "GA4 metadata failed.", "google_response": data})
    data["property_id"] = resolved_property_id
    return data
