from typing import Any

import pandas as pd


def normalize_ga4_report(payload: dict[str, Any]) -> list[dict[str, Any]]:
    dimension_headers = [item.get("name") for item in payload.get("dimensionHeaders", [])]
    metric_headers = [item.get("name") for item in payload.get("metricHeaders", [])]
    rows = []
    for row in payload.get("rows", []) or []:
        item = {}
        for idx, header in enumerate(dimension_headers):
            values = row.get("dimensionValues", [])
            item[header] = values[idx].get("value") if idx < len(values) else None
        for idx, header in enumerate(metric_headers):
            values = row.get("metricValues", [])
            raw = values[idx].get("value") if idx < len(values) else None
            item[header] = _coerce_number(raw)
        rows.append(item)
    return rows


def ga4_frame(payload: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(normalize_ga4_report(payload))


def _coerce_number(value: Any) -> Any:
    if value is None:
        return None
    text = str(value)
    try:
        if "." in text:
            return float(text)
        return int(text)
    except ValueError:
        try:
            return float(text)
        except ValueError:
            return value


def total_metric(rows: list[dict[str, Any]], metric: str) -> float:
    total = 0.0
    for row in rows:
        value = row.get(metric)
        if isinstance(value, (int, float)):
            total += float(value)
    return total


def collect_event_names(rows: list[dict[str, Any]]) -> set[str]:
    return {str(row.get("eventName") or "").strip() for row in rows if row.get("eventName")}
