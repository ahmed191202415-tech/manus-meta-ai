def build_journey_signals(metrics: dict, matching: dict, website_signals: list[dict]) -> list[dict]:
    signals = []
    confidence = "medium" if matching.get("matching_confidence") in {"medium", "high"} else "low"

    if metrics.get("meta_clicks", 0) >= 100 and metrics.get("click_to_session_rate", 0) < 0.5:
        signals.append(_signal("click_session_loss", "high", confidence, {"click_to_session_rate": metrics.get("click_to_session_rate"), "meta_clicks": metrics.get("meta_clicks"), "ga4_sessions": metrics.get("ga4_sessions")}, "Check landing URL, UTM tracking, redirects, page load, and GA4 session attribution."))

    if metrics.get("session_to_engaged_rate", 0) < 0.3 and metrics.get("ga4_sessions", 0) >= 100:
        signals.append(_signal("ad_good_site_weak", "high", confidence, {"session_to_engaged_rate": metrics.get("session_to_engaged_rate"), "ga4_sessions": metrics.get("ga4_sessions")}, "Do not scale budget before fixing landing page engagement."))

    if metrics.get("session_to_engaged_rate", 0) >= 0.5 and metrics.get("session_to_conversion_rate", 0) < 0.005:
        signals.append(_signal("engaged_no_conversion", "medium", confidence, {"engaged_to_conversion_rate": metrics.get("engaged_to_conversion_rate")}, "Users engage but do not convert; inspect CTA, offer, forms, and trust signals."))

    if metrics.get("pixel_ga4_gap_rate", 0) > 0.5:
        signals.append(_signal("pixel_ga4_gap", "high", "medium", {"pixel_ga4_gap_rate": metrics.get("pixel_ga4_gap_rate"), "meta_pixel_leads": metrics.get("meta_pixel_leads"), "ga4_conversions": metrics.get("ga4_conversions")}, "Do not combine Meta leads and GA4 conversions; inspect attribution and tracking."))

    if matching.get("matching_confidence") in {"low", "unavailable"}:
        signals.append(_signal("ad_to_page_match_low_confidence", "medium", "low", matching, "Add campaign/ad identifiers to UTM or GA4 custom dimensions before ad-level decisions."))

    for item in website_signals:
        if item.get("signal") == "mobile_underperformance":
            signals.append(_signal("mobile_paid_social_issue", item.get("severity", "medium"), item.get("confidence", confidence), item.get("evidence", {}), "Fix mobile UX before scaling paid social."))

    return signals


def _signal(signal: str, severity: str, confidence: str, evidence: dict, decision_hint: str) -> dict:
    return {
        "signal": signal,
        "severity": severity,
        "confidence": confidence,
        "evidence": evidence,
        "decision_hint": decision_hint,
    }
