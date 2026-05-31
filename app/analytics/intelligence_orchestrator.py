def orchestrate_intelligence(meta_result: dict | None = None, website_result: dict | None = None, journey_result: dict | None = None) -> dict:
    if journey_result:
        mode = "meta_ga4_journey"
        source = journey_result
    elif website_result:
        mode = "ga4_only"
        source = website_result
    else:
        mode = "meta_only"
        source = meta_result or {}

    signals = source.get("signals", [])
    confidence = _confidence(signals, source.get("tracking_quality") or source.get("data_quality") or {})
    return {
        "mode": mode,
        "summary_metrics": source.get("summary_metrics") or source.get("result") or {},
        "analyst_brief": source.get("analyst_brief") or {},
        "goal_context": source.get("goal_context") or (source.get("analyst_brief") or {}).get("goal_context") or {},
        "data_quality": source.get("tracking_quality") or source.get("data_quality") or {},
        "signals": signals,
        "ranked_issues": sorted(signals, key=lambda item: _severity_weight(item.get("severity")), reverse=True),
        "decision_hints": source.get("decision_hints") or [item.get("decision_hint") for item in signals if item.get("decision_hint")],
        "missing_data": source.get("missing_data") or [],
        "confidence": confidence,
    }


def _severity_weight(severity: str | None) -> int:
    return {"critical": 4, "high": 3, "medium": 2, "low": 1}.get(str(severity or "").lower(), 0)


def _confidence(signals: list[dict], quality: dict) -> str:
    if quality.get("level") == "weak":
        return "low"
    if any(item.get("confidence") == "high" for item in signals):
        return "high"
    if signals:
        return "medium"
    return "low"
