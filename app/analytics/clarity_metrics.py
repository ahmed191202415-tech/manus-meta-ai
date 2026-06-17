FRUSTRATION_KEYS = [
    "deadClickCount",
    "Dead Click Count",
    "rageClickCount",
    "Rage Click Count",
    "quickbackClick",
    "Quickback Click",
    "scriptErrorCount",
    "Script Error Count",
    "errorClickCount",
    "Error Click Count",
]
FRUSTRATION_METRICS = {
    "DeadClickCount",
    "RageClickCount",
    "QuickbackClick",
    "ScriptErrorCount",
    "ErrorClickCount",
    "Dead Click Count",
    "Rage Click Count",
    "Quickback Click",
    "Script Error Count",
    "Error Click Count",
}


def normalize_clarity_export(payload: dict) -> list[dict]:
    rows = []
    for metric_block in payload.get("raw") or []:
        metric_name = metric_block.get("metricName")
        for item in metric_block.get("information") or []:
            row = {"metricName": metric_name, **item}
            if row.get("Url") and not row.get("URL"):
                row["URL"] = row.get("Url")
            if row.get("sessionsCount") is not None and row.get("totalSessionCount") is None:
                row["totalSessionCount"] = row.get("sessionsCount")
            rows.append(row)
    return rows


def summarize_clarity_metrics(rows: list[dict]) -> dict:
    sessions = _estimate_sessions(rows)
    bot_sessions = sum(_num(row.get("totalBotSessionCount")) for row in rows if row.get("metricName") == "Traffic")
    dead_click_events = _clarity_event_total(rows, {"DeadClickCount", "Dead Click Count"}, ["deadClickCount", "Dead Click Count"])
    rage_click_events = _clarity_event_total(rows, {"RageClickCount", "Rage Click Count"}, ["rageClickCount", "Rage Click Count"])
    quickback_events = _clarity_event_total(rows, {"QuickbackClick", "Quickback Click"}, ["quickbackClick", "Quickback Click"])
    script_error_events = _clarity_event_total(rows, {"ScriptErrorCount", "Script Error Count"}, ["scriptErrorCount", "Script Error Count"])
    frustration = sum(_num(row.get("subTotal")) for row in rows if row.get("metricName") in FRUSTRATION_METRICS)
    frustration += sum(sum(_num(row.get(key)) for key in FRUSTRATION_KEYS) for row in rows)
    scroll_values = _metric_values(rows, {"ScrollDepth", "Scroll Depth"}, ["scrollDepth", "Scroll Depth"])
    active_time_values = _metric_values(rows, {"EngagementTime", "Engagement Time"}, ["engagementTime", "Engagement Time", "activeTime"])
    return {
        "clarity_sessions": sessions,
        "bot_sessions": bot_sessions,
        "bot_session_rate": _safe_div(bot_sessions, sessions + bot_sessions),
        "frustration_events": frustration,
        "frustration_rate": _safe_div(frustration, sessions),
        "dead_click_events": dead_click_events,
        "rage_click_events": rage_click_events,
        "quickback_events": quickback_events,
        "script_error_events": script_error_events,
        "average_scroll_depth": _avg(scroll_values),
        "average_active_time": _avg(active_time_values),
        "row_count": len(rows),
        "missing_metrics": _missing(rows),
    }


def top_clarity_entities(rows: list[dict], key: str = "URL", limit: int = 10) -> list[dict]:
    items = [row for row in rows if row.get(key)]
    return sorted(items, key=lambda row: _num(row.get("totalSessionCount") or row.get("sessionsCount")), reverse=True)[:limit]


def _num(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


def _missing(rows: list[dict]) -> list[str]:
    keys = {key for row in rows for key in row.keys()}
    metric_names = {row.get("metricName") for row in rows}
    expected = {"totalSessionCount", "ScrollDepth", "EngagementTime", "DeadClickCount", "RageClickCount"}
    present = keys | metric_names
    return sorted(expected - present)


def _estimate_sessions(rows: list[dict]) -> float:
    traffic_sessions = sum(_num(row.get("totalSessionCount") or row.get("sessionsCount")) for row in rows if row.get("metricName") == "Traffic")
    if traffic_sessions:
        return traffic_sessions
    by_metric = {}
    for row in rows:
        metric = row.get("metricName") or "unknown"
        by_metric[metric] = by_metric.get(metric, 0.0) + _num(row.get("totalSessionCount") or row.get("sessionsCount"))
    return max(by_metric.values(), default=0.0)


def _metric_values(rows: list[dict], metric_names: set[str], field_names: list[str]) -> list[float]:
    values = []
    for row in rows:
        if row.get("metricName") in metric_names and row.get("subTotal") is not None:
            values.append(_num(row.get("subTotal")))
            continue
        for field in field_names:
            if row.get(field) is not None:
                values.append(_num(row.get(field)))
                break
    return values


def _clarity_event_total(rows: list[dict], metric_names: set[str], field_names: list[str]) -> float:
    total = 0.0
    for row in rows:
        if row.get("metricName") in metric_names:
            total += _num(row.get("subTotal"))
            continue
        for field in field_names:
            if row.get(field) is not None:
                total += _num(row.get(field))
    return total
