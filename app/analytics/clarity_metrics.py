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


def normalize_clarity_export(payload: dict) -> list[dict]:
    rows = []
    for metric_block in payload.get("raw") or []:
        metric_name = metric_block.get("metricName")
        for item in metric_block.get("information") or []:
            rows.append({"metricName": metric_name, **item})
    return rows


def summarize_clarity_metrics(rows: list[dict]) -> dict:
    sessions = sum(_num(row.get("totalSessionCount")) for row in rows if row.get("totalSessionCount") is not None)
    bot_sessions = sum(_num(row.get("totalBotSessionCount")) for row in rows if row.get("totalBotSessionCount") is not None)
    frustration = sum(sum(_num(row.get(key)) for key in FRUSTRATION_KEYS) for row in rows)
    scroll_values = [_num(row.get("scrollDepth") or row.get("Scroll Depth")) for row in rows if row.get("scrollDepth") is not None or row.get("Scroll Depth") is not None]
    active_time_values = [_num(row.get("engagementTime") or row.get("Engagement Time") or row.get("activeTime")) for row in rows if row.get("engagementTime") is not None or row.get("Engagement Time") is not None or row.get("activeTime") is not None]
    return {
        "clarity_sessions": sessions,
        "bot_sessions": bot_sessions,
        "bot_session_rate": _safe_div(bot_sessions, sessions + bot_sessions),
        "frustration_events": frustration,
        "frustration_rate": _safe_div(frustration, sessions),
        "average_scroll_depth": _avg(scroll_values),
        "average_active_time": _avg(active_time_values),
        "row_count": len(rows),
        "missing_metrics": _missing(rows),
    }


def top_clarity_entities(rows: list[dict], key: str = "URL", limit: int = 10) -> list[dict]:
    items = [row for row in rows if row.get(key)]
    return sorted(items, key=lambda row: _num(row.get("totalSessionCount")), reverse=True)[:limit]


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
    expected = {"totalSessionCount", "scrollDepth", "engagementTime", "deadClickCount", "rageClickCount"}
    return sorted(expected - keys)
