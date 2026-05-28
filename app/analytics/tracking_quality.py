from app.analytics.ga4_preprocessing import collect_event_names, total_metric


IMPORTANT_EVENTS = {
    "purchase",
    "generate_lead",
    "form_submit",
    "add_to_cart",
    "begin_checkout",
}


def build_tracking_quality(
    connected: bool,
    property_selected: bool,
    traffic_rows: list[dict],
    landing_page_rows: list[dict],
    event_rows: list[dict],
) -> dict:
    strengths = []
    weaknesses = []
    analysis_limits = []

    if connected:
        strengths.append("GA4 connected")
    else:
        weaknesses.append("GA4 is not connected")
    if property_selected:
        strengths.append("GA4 property selected")
    else:
        weaknesses.append("GA4 property not selected")

    sessions = total_metric(traffic_rows, "sessions")
    if sessions > 0:
        strengths.append("Sessions are available")
    else:
        weaknesses.append("No sessions found")
        analysis_limits.append("Cannot analyze traffic volume for this date range")

    if landing_page_rows:
        strengths.append("Landing pages available")
    else:
        weaknesses.append("No landing page data")

    source_medium_count = len({row.get("sessionSourceMedium") for row in traffic_rows if row.get("sessionSourceMedium")})
    if source_medium_count:
        strengths.append("Traffic sources available")
    else:
        weaknesses.append("No source/medium data")

    event_names = collect_event_names(event_rows)
    if event_names:
        strengths.append("Events are available")
    else:
        weaknesses.append("No events found")

    missing_events = sorted(event for event in IMPORTANT_EVENTS if event not in event_names)
    if "generate_lead" not in event_names and "form_submit" not in event_names:
        weaknesses.append("No clear lead event")
        analysis_limits.append("Cannot accurately analyze lead funnel")
    if "purchase" not in event_names:
        weaknesses.append("No purchase event")

    score = 100
    score -= 25 if not connected else 0
    score -= 15 if not property_selected else 0
    score -= 20 if sessions <= 0 else 0
    score -= 10 if not landing_page_rows else 0
    score -= 10 if not source_medium_count else 0
    score -= 10 if not event_names else 0
    score -= min(len(missing_events) * 3, 15)
    score = max(0, min(100, score))

    if score >= 75:
        level = "good"
    elif score >= 45:
        level = "medium"
    else:
        level = "weak"

    return {
        "tracking_score": score,
        "score": score,
        "level": level,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "analysis_limits": analysis_limits,
        "missing_metrics": [],
        "missing_events": missing_events,
    }
