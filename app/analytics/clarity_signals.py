def build_clarity_signals(summary: dict, rows: list[dict]) -> list[dict]:
    signals = []
    sessions = summary.get("clarity_sessions", 0)
    if sessions < 30:
        signals.append(_signal("clarity_sample_size_low", "low", "high", {"sessions": sessions}, "Use Clarity directionally until more sessions are collected."))
    if summary.get("frustration_rate", 0) > 0.08 and sessions >= 30:
        signals.append(_signal("high_user_frustration", "high", "medium", {"frustration_rate": summary.get("frustration_rate"), "frustration_events": summary.get("frustration_events")}, "Inspect rage/dead/error clicks on landing pages before scaling traffic."))
    if 0 < summary.get("average_scroll_depth", 0) < 35 and sessions >= 30:
        signals.append(_signal("low_scroll_depth", "medium", "medium", {"average_scroll_depth": summary.get("average_scroll_depth")}, "Move the key CTA and value proof higher on the page."))
    if summary.get("bot_session_rate", 0) > 0.25:
        signals.append(_signal("high_bot_traffic", "medium", "medium", {"bot_session_rate": summary.get("bot_session_rate")}, "Separate bot traffic before judging landing page quality."))

    mobile_rows = [row for row in rows if str(row.get("Device") or "").lower() in {"mobile", "phone"}]
    if mobile_rows and any(_num(row.get("deadClickCount") or row.get("rageClickCount")) > 0 for row in mobile_rows):
        signals.append(_signal("mobile_ux_friction", "high", "medium", {"rows": mobile_rows[:5]}, "Inspect mobile recordings for broken taps, confusing CTA, or layout issues."))
    return signals


def _signal(signal: str, severity: str, confidence: str, evidence: dict, decision_hint: str) -> dict:
    return {
        "signal": signal,
        "severity": severity,
        "confidence": confidence,
        "evidence": evidence,
        "decision_hint": decision_hint,
    }


def _num(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0
