from app.analytics.signal_scoring import confidence_from_quality, severity_from_gap
from app.analytics.website_metrics import safe_div


def build_website_signals(
    summary: dict,
    tracking_quality: dict,
    landing_pages: list[dict],
    traffic_sources: list[dict],
    devices: list[dict],
) -> list[dict]:
    signals = []
    sessions = float(summary.get("sessions") or 0)
    confidence = confidence_from_quality(tracking_quality, sessions)

    if sessions < 100:
        signals.append(_signal("sample_size_too_low", "medium", "low", {"sessions": sessions}, [], [], "Collect more data before strong decisions."))

    if "No clear lead event" in tracking_quality.get("weaknesses", []):
        signals.append(_signal("missing_conversion_tracking", "high", "high", {"missing_events": tracking_quality.get("missing_events", [])}, [], tracking_quality.get("missing_events", []), "Fix conversion tracking before judging performance."))

    for row in landing_pages[:10]:
        row_sessions = float(row.get("sessions") or 0)
        engagement_rate = float(row.get("engagementRate") or safe_div(float(row.get("engagedSessions") or 0), row_sessions))
        conversion_rate = safe_div(float(row.get("conversions") or 0), row_sessions)
        page = row.get("landingPagePlusQueryString") or row.get("landingPage") or "(not set)"
        if row_sessions >= 100 and engagement_rate < 0.25:
            signals.append(_signal("low_landing_page_engagement", "high", confidence, {"sessions": row_sessions, "engagement_rate": engagement_rate}, [{"type": "landing_page", "value": page}], [], "Review page speed, message match, first screen, and content relevance."))
        if row_sessions >= 100 and conversion_rate < 0.005 and tracking_quality.get("level") != "weak":
            signals.append(_signal("high_sessions_low_conversion", "high", confidence, {"sessions": row_sessions, "conversion_rate": conversion_rate}, [{"type": "landing_page", "value": page}], [], "Investigate offer, CTA, form, trust, and pricing."))
        if row_sessions >= 100 and engagement_rate >= 0.55 and conversion_rate < 0.005:
            signals.append(_signal("high_engagement_low_conversion", "medium", confidence, {"sessions": row_sessions, "engagement_rate": engagement_rate, "conversion_rate": conversion_rate}, [{"type": "landing_page", "value": page}], [], "Users are interested but not converting; inspect CTA and form friction."))

    mobile = _device(devices, "mobile")
    desktop = _device(devices, "desktop")
    if mobile and desktop:
        mobile_rate = safe_div(float(mobile.get("conversions") or 0), float(mobile.get("sessions") or 0))
        desktop_rate = safe_div(float(desktop.get("conversions") or 0), float(desktop.get("sessions") or 0))
        gap = desktop_rate - mobile_rate
        if float(mobile.get("sessions") or 0) >= 100 and gap > 0.01:
            signals.append(_signal("mobile_underperformance", severity_from_gap(gap, 0.03, 0.01), confidence, {"mobile_conversion_rate": mobile_rate, "desktop_conversion_rate": desktop_rate, "gap": gap}, [{"type": "device", "value": "mobile"}], [], "Check mobile speed, form UX, layout, and payment/lead friction."))

    if traffic_sources:
        top_sessions = max(float(row.get("sessions") or 0) for row in traffic_sources)
        if sessions and top_sessions / sessions >= 0.65:
            signals.append(_signal("traffic_source_dependency", "medium", confidence, {"top_source_share": round(top_sessions / sessions, 4), "sessions": sessions}, [], [], "Diversify acquisition or reduce dependency on one source."))

    return signals


def _signal(signal: str, severity: str, confidence: str, evidence: dict, affected_entities: list[dict], missing_data: list, decision_hint: str) -> dict:
    return {
        "signal": signal,
        "severity": severity,
        "confidence": confidence,
        "evidence": evidence,
        "affected_entities": affected_entities,
        "missing_data": missing_data,
        "decision_hint": decision_hint,
    }


def _device(rows: list[dict], name: str) -> dict:
    for row in rows:
        if str(row.get("deviceCategory") or "").lower() == name:
            return row
    return {}
