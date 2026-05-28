from app.analytics.ga4_preprocessing import total_metric


def safe_div(a: float, b: float) -> float:
    return round(float(a) / float(b), 6) if b else 0.0


def summarize_website_metrics(
    traffic_rows: list[dict],
    landing_page_rows: list[dict] | None = None,
    event_rows: list[dict] | None = None,
    device_rows: list[dict] | None = None,
) -> dict:
    landing_page_rows = landing_page_rows or []
    event_rows = event_rows or []
    device_rows = device_rows or []

    sessions = total_metric(traffic_rows, "sessions")
    active_users = total_metric(traffic_rows, "activeUsers")
    engaged_sessions = total_metric(traffic_rows, "engagedSessions")
    conversions = total_metric(traffic_rows, "conversions")
    total_revenue = total_metric(traffic_rows, "totalRevenue")
    event_count = total_metric(event_rows, "eventCount")

    mobile = _find_device(device_rows, "mobile")
    desktop = _find_device(device_rows, "desktop")
    mobile_conversion_rate = safe_div(float(mobile.get("conversions", 0) or 0), float(mobile.get("sessions", 0) or 0))
    desktop_conversion_rate = safe_div(float(desktop.get("conversions", 0) or 0), float(desktop.get("sessions", 0) or 0))

    missing_metrics = []
    for metric in ["sessions", "engagedSessions", "conversions", "totalRevenue"]:
        if traffic_rows and metric not in traffic_rows[0]:
            missing_metrics.append(metric)

    return {
        "sessions": sessions,
        "users": active_users,
        "active_users": active_users,
        "engaged_sessions": engaged_sessions,
        "engagement_rate": safe_div(engaged_sessions, sessions),
        "conversions": conversions,
        "conversion_rate": safe_div(conversions, sessions),
        "total_revenue": total_revenue,
        "revenue_per_session": safe_div(total_revenue, sessions),
        "event_count": event_count,
        "landing_page_count": len(landing_page_rows),
        "traffic_source_count": len(traffic_rows),
        "mobile_conversion_rate": mobile_conversion_rate,
        "desktop_conversion_rate": desktop_conversion_rate,
        "mobile_desktop_gap": round(desktop_conversion_rate - mobile_conversion_rate, 6),
        "missing_metrics": missing_metrics,
    }


def top_entities(rows: list[dict], sort_metric: str = "sessions", limit: int = 10) -> list[dict]:
    return sorted(rows or [], key=lambda item: float(item.get(sort_metric) or 0), reverse=True)[:limit]


def _find_device(rows: list[dict], device: str) -> dict:
    for row in rows:
        if str(row.get("deviceCategory") or "").lower() == device:
            return row
    return {}
