from __future__ import annotations

from datetime import date, timedelta
from typing import Any


CONNECTOR_REGISTRY = {
    "meta": {
        "type": "meta_ads",
        "supports": ["accounts", "campaigns", "adsets", "ads", "insights", "actions", "pixel_events", "custom_conversions"],
    },
    "ga4": {
        "type": "ga4",
        "supports": ["events", "pages", "traffic_sources", "devices", "funnels", "custom_reports"],
    },
    "clarity": {
        "type": "clarity",
        "supports": ["pages", "quickback", "dead_click", "rage_click", "script_error", "avg_active_time"],
    },
}


METRIC_DICTIONARY = {
    "spend": {"source": "meta", "field": "spend"},
    "unique_ctr": {"source": "meta", "field": "unique_ctr"},
    "unique_link_clicks": {"source": "meta", "field": "unique_inline_link_clicks"},
    "landing_loaded": {
        "source": "meta_action",
        "action_type": "landing_page_view",
        "fallback_action_type": "omni_landing_page_view",
        "fallback_mode": "use_first_available_not_sum",
    },
    "stayed_10s": {"source": "ga4", "event_name": "landing_stayed_10s"},
    "scroll_50": {"source": "ga4", "event_name": "Scroll - BeOn Landing 50"},
    "quickback": {"source": "clarity", "field": "quickback"},
    "dead_click": {"source": "clarity", "field": "dead_click"},
    "script_error": {"source": "clarity", "field": "script_error"},
    "register_page": {"source": "meta_event", "event_name": "Register Page", "match_mode": "exact", "fallback_policy": "none"},
    "otp": {"source": "meta_event", "event_name": "OTP"},
    "complete_profile": {"source": "meta_event", "event_name": "Complete Profile"},
    "start_trial": {"source": "meta_event", "event_name": "Start Trial"},
    "complete_registration": {
        "source": "meta_action",
        "action_type": "complete_registration",
        "fallback_action_type": "omni_complete_registration",
        "fallback_mode": "use_first_available_not_sum",
    },
    "purchase": {
        "source": "meta_action",
        "action_type": "purchase",
        "fallback_action_type": "omni_purchase",
        "fallback_mode": "use_first_available_not_sum",
    },
}


DEFAULT_DASHBOARD_DEFINITION = {
    "dashboard_id": "customer_journey",
    "title": "Customer Journey Intelligence Dashboard",
    "filters": [
        {"key": "date_range", "type": "date_range", "applies_to": ["meta", "ga4", "clarity"]},
        {"key": "campaign_id", "type": "select", "source": "meta.campaigns", "optional": True},
        {"key": "adset_id", "type": "select", "source": "meta.adsets", "optional": True},
        {"key": "ad_id", "type": "select", "source": "meta.ads", "optional": True},
        {"key": "device", "type": "select", "source": "ga4.deviceCategory", "optional": True},
        {"key": "placement", "type": "select", "source": "meta.publisher_platform", "optional": True},
    ],
    "data_sources": {
        "meta": {"connector": "meta_ads", "account_id": "act_763606732391242"},
        "ga4": {"connector": "ga4", "property_id": "529884683"},
        "clarity": {"connector": "clarity"},
    },
    "charts": [
        {"id": "conversion_path", "type": "conversion_path", "data_query": "journey_funnel"},
        {"id": "stage_inspector", "type": "stage_breakdown", "depends_on": "selected_stage"},
        {"id": "trend_analysis", "type": "line_chart", "data_query": "journey_trend"},
        {"id": "comparison_lab", "type": "comparison_builder", "data_query": "journey_comparison"},
    ],
    "metrics": METRIC_DICTIONARY,
    "stages": [
        {"id": "unique_ctr", "label": "Unique CTR", "metric_id": "unique_ctr", "position": 1},
        {"id": "unique_link_clicks", "label": "Unique Link Clicks", "metric_id": "unique_link_clicks", "position": 2},
        {"id": "landing_loaded", "label": "Landing Loaded", "metric_id": "landing_loaded", "position": 3},
        {"id": "register_page", "label": "Register Page", "metric_id": "register_page", "position": 4},
        {"id": "complete_registration", "label": "Complete Registration", "metric_id": "complete_registration", "position": 5},
        {"id": "purchase", "label": "Purchase", "metric_id": "purchase", "position": 6},
    ],
    "widgets": [
        {"id": "conversion_path", "type": "conversion_path", "title": "Conversion Path", "stages": ["unique_ctr", "unique_link_clicks", "landing_loaded", "register_page", "complete_registration", "purchase"]},
        {"id": "stage_inspector", "type": "stage_inspector", "depends_on": "selected_stage"},
    ],
}


def safe_div(numerator: float, denominator: float) -> float | None:
    if not denominator:
        return None
    return numerator / denominator


def pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.1f}%"


def money(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}"


def build_query_plan(definition: dict, query_id: str | None = None) -> dict:
    metrics = _metrics_for_query(query_id, definition)
    calls = []
    metric_defs = _definition_metrics(definition)
    for metric in metrics:
        meta = metric_defs.get(metric, {})
        source = meta.get("source")
        if source in {"meta", "meta_action", "meta_event"}:
            calls.append({"source": "meta", "metric": metric, "method": "insights/actions", "spec": meta})
        elif source == "ga4":
            calls.append({"source": "ga4", "metric": metric, "method": "custom_report/events", "spec": meta})
        elif source == "clarity":
            calls.append({"source": "clarity", "metric": metric, "method": "project-live-insights", "spec": meta})
    return {
        "dashboard_id": definition.get("dashboard_id"),
        "query_id": query_id,
        "metrics": metrics,
        "calls": calls,
        "merge_strategy": "stage_id",
        "formulas": ["transition_rate", "drop_rate", "cost_per_stage", "final_conversion_rate", "strength_score"],
    }


def _metrics_for_query(query_id: str | None, definition: dict | None = None) -> list[str]:
    if query_id in {None, "journey_funnel"} and definition:
        stages = _definition_stages(definition)
        if stages:
            return [stage.get("metric_id") or stage.get("id") for stage in stages if stage.get("metric_id") or stage.get("id")]
    if query_id == "journey_trend":
        return ["spend", "register_page", "otp", "complete_profile", "start_trial"]
    if query_id == "journey_comparison":
        return ["spend", "unique_ctr", "unique_link_clicks", "register_page", "otp", "complete_profile"]
    return [
        "unique_ctr",
        "unique_link_clicks",
        "landing_loaded",
        "stayed_10s",
        "scroll_50",
        "quickback",
        "dead_click",
        "script_error",
        "register_page",
        "otp",
        "complete_profile",
        "start_trial",
    ]


def build_fallback_funnel(filters: dict | None = None) -> dict:
    filters = filters or {}
    spend = 1260.60
    stage_values = [
        ("unique_ctr", "Unique CTR", 1.37, "meta", None),
        ("unique_link_clicks", "Unique Link Clicks", 129, "meta", spend / 129),
        ("landing_loaded", "Landing Loaded", 263, "ga4", spend / 263),
        ("engaged", "Engaged Visitor", 213, "ga4_clarity", spend / 213),
        ("register_page", "Register Page", 9, "meta_event", spend / 9),
        ("otp", "OTP", 3, "meta_event", spend / 3),
        ("complete_profile", "Complete Profile", 0, "meta_event", None),
        ("start_trial", "Start Trial", 0, "meta_event", None),
    ]
    stages = []
    previous = None
    for stage_id, label, value, source, cost in stage_values:
        numeric_value = float(value or 0)
        transition = 1 if previous is None else safe_div(numeric_value, previous)
        drop = None if transition is None else max(0, 1 - transition)
        stages.append(
            {
                "id": stage_id,
                "label": label,
                "value": pct(numeric_value / 100) if stage_id == "unique_ctr" else int(numeric_value),
                "numeric_value": numeric_value,
                "source": source,
                "cost": None if cost is None else round(cost, 2),
                "transition_rate": transition,
                "transition_label": pct(transition),
                "drop_rate": drop,
                "drop_label": pct(drop),
                "status": _stage_status(drop, transition),
                "metric_source": METRIC_DICTIONARY.get(stage_id, {"source": source}),
            }
        )
        if stage_id != "unique_ctr":
            previous = numeric_value
    return {
        "filters": filters,
        "spend": spend,
        "stages": stages,
        "summary": {
            "first_stage": "unique_ctr",
            "final_stage": "start_trial",
            "final_conversion_rate": safe_div(stages[-1]["numeric_value"], stages[1]["numeric_value"]),
        },
        "debug": {
            "mode": "fallback_data",
            "filters_sent": filters,
            "message": "Live connector data was not required for this preview response.",
            "query_plan": build_query_plan(DEFAULT_DASHBOARD_DEFINITION, "journey_funnel"),
        },
    }


def build_live_funnel(
    meta_insights_payload: dict,
    filters: dict | None = None,
    *,
    definition: dict | None = None,
    debug: dict | None = None,
    mode: str = "live_data",
) -> dict:
    filters = filters or {}
    definition = definition or DEFAULT_DASHBOARD_DEFINITION
    rows = meta_insights_payload.get("data") or []
    row = rows[0] if rows else {}
    external_metrics = {
        "ga4": meta_insights_payload.get("_ga4_metrics") or {},
        "clarity": meta_insights_payload.get("_clarity_metrics") or {},
    }
    spend = _number(row.get("spend"))
    metric_defs = _definition_metrics(definition)
    resolved_metrics = {}
    resolver_warnings = []
    for metric_id, metric_definition in metric_defs.items():
        resolved = resolve_metric(metric_definition, row, external_metrics)
        resolved_metrics[metric_id] = resolved
        resolver_warnings.extend(resolved.get("warnings") or [])

    stage_values = []
    for stage in _definition_stages(definition):
        metric_id = stage.get("metric_id") or stage.get("id")
        resolved = resolved_metrics.get(metric_id) or {"value": 0, "metric_source": {"resolved": False}, "warnings": [f"Metric not defined: {metric_id}"]}
        stage_values.append(
            (
                stage.get("id") or metric_id,
                stage.get("label") or metric_id,
                _number(resolved.get("value")),
                str(resolved.get("metric_source", {}).get("source") or "unknown"),
                _cost(spend, _number(resolved.get("value"))),
                resolved.get("metric_source") or {},
                resolved.get("warnings") or [],
            )
        )
    stages = _build_stage_rows(stage_values)
    unmapped_events = _unmapped_custom_events(row, metric_defs)
    missing_live_metrics = [
        stage["id"]
        for stage in stages
        if stage["numeric_value"] == 0 and stage["id"] not in {"complete_profile", "start_trial", "otp"}
    ]
    return {
        "filters": filters,
        "spend": round(spend, 2),
        "stages": stages,
        "summary": {
            "first_stage": "unique_ctr",
            "final_stage": "start_trial",
            "final_conversion_rate": safe_div(stages[-1]["numeric_value"], stages[1]["numeric_value"]),
            "raw_meta": {
                "impressions": _number(row.get("impressions")),
                "reach": _number(row.get("reach")),
                "clicks": _number(row.get("clicks")),
                "inline_link_clicks": _number(row.get("inline_link_clicks")),
                "unique_inline_link_clicks": _number(row.get("unique_inline_link_clicks")),
                "leads": _action_value(row, "lead"),
            },
        },
        "debug": {
            "mode": mode,
            "filters_sent": filters,
            "query_plan": build_query_plan(definition, "journey_funnel"),
            "meta_insights_rows": len(rows),
            "missing_live_metrics": missing_live_metrics,
            "warnings": resolver_warnings,
            "unmapped_events": unmapped_events,
            "manifest_driven": True,
            **(debug or {}),
        },
    }


def build_mixed_funnel(live_payload: dict | None, filters: dict | None = None, debug: dict | None = None, definition: dict | None = None) -> dict:
    if not live_payload:
        fallback = build_fallback_funnel(filters)
        fallback["debug"]["connector_errors"] = (debug or {}).get("connector_errors", [])
        return fallback
    return build_live_funnel(live_payload, filters, definition=definition, debug=debug, mode=(debug or {}).get("mode", "live_data"))


def _build_stage_rows(stage_values: list[tuple]) -> list[dict]:
    stages = []
    previous = None
    for item in stage_values:
        stage_id, label, value, source, cost = item[:5]
        metric_source = item[5] if len(item) > 5 else METRIC_DICTIONARY.get(stage_id, {"source": source})
        warnings = item[6] if len(item) > 6 else []
        numeric_value = float(value or 0)
        transition = 1 if previous is None else safe_div(numeric_value, previous)
        drop = None if transition is None else max(0, 1 - transition)
        stages.append(
            {
                "id": stage_id,
                "label": label,
                "value": pct(numeric_value / 100) if stage_id == "unique_ctr" else int(numeric_value),
                "numeric_value": numeric_value,
                "source": source,
                "cost": None if cost is None else round(cost, 2),
                "transition_rate": transition,
                "transition_label": pct(transition),
                "drop_rate": drop,
                "drop_label": pct(drop),
                "status": _stage_status(drop, transition),
                "metric_source": metric_source,
                "warnings": warnings,
            }
        )
        if stage_id != "unique_ctr":
            previous = numeric_value
    return stages


def _number(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, list):
        return sum(_number(item.get("value") if isinstance(item, dict) else item) for item in value)
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _cost(spend: float, value: float) -> float | None:
    return safe_div(spend, value)


def _action_value(row: dict, action_type: str) -> float:
    target = str(action_type or "").casefold()
    total = 0.0
    for item in row.get("actions") or []:
        current = str(item.get("action_type") or item.get("event_name") or "").casefold()
        if current == target or target in current:
            total += _number(item.get("value"))
    return total


def resolve_metric(metric_definition: dict, raw_meta_row: dict, external_metrics: dict | None = None) -> dict:
    source = str(metric_definition.get("source") or "").strip()
    if source == "meta" and metric_definition.get("field"):
        field = str(metric_definition["field"])
        value = _number(raw_meta_row.get(field))
        return {
            "value": value,
            "metric_source": {**metric_definition, "resolved": raw_meta_row.get(field) is not None, "resolved_field": field},
            "warnings": [] if raw_meta_row.get(field) is not None else [f"Field not found: {field}"],
        }

    if source in {"meta_action", "meta_event"}:
        return _resolve_action_metric(metric_definition, raw_meta_row)

    if source == "ga4":
        return _resolve_ga4_metric(metric_definition, (external_metrics or {}).get("ga4") or {})

    if source == "clarity":
        return _resolve_clarity_metric(metric_definition, (external_metrics or {}).get("clarity") or {})

    return {
        "value": 0,
        "metric_source": {**metric_definition, "resolved": False},
        "warnings": [f"Unsupported metric source: {source or 'missing'}"],
    }


def _resolve_ga4_metric(metric_definition: dict, ga4_metrics: dict) -> dict:
    event_name = str(metric_definition.get("event_name") or "").strip()
    field = str(metric_definition.get("field") or "").strip()
    if event_name:
        events = ga4_metrics.get("events") or {}
        value = _number(events.get(event_name))
        return {
            "value": value,
            "metric_source": {**metric_definition, "resolved": event_name in events, "resolved_event_name": event_name},
            "warnings": [] if event_name in events else [f"GA4 event not found: {event_name}"],
        }
    if field:
        summary = ga4_metrics.get("summary") or {}
        value = _number(summary.get(field))
        return {
            "value": value,
            "metric_source": {**metric_definition, "resolved": field in summary, "resolved_field": field},
            "warnings": [] if field in summary else [f"GA4 field not found: {field}"],
        }
    return {
        "value": 0,
        "metric_source": {**metric_definition, "resolved": False},
        "warnings": ["GA4 metric needs event_name or field"],
    }


def _resolve_clarity_metric(metric_definition: dict, clarity_metrics: dict) -> dict:
    field = str(metric_definition.get("field") or "").strip()
    aliases = {
        "quickback": "quickback_events",
        "quickback_click": "quickback_events",
        "dead_click": "dead_click_events",
        "deadclick": "dead_click_events",
        "rage_click": "rage_click_events",
        "script_error": "script_error_events",
        "avg_active_time": "average_active_time",
        "average_active_time": "average_active_time",
        "scroll_depth": "average_scroll_depth",
        "average_scroll_depth": "average_scroll_depth",
        "sessions": "clarity_sessions",
    }
    resolved_field = aliases.get(field.casefold(), field)
    summary = clarity_metrics.get("summary") or clarity_metrics
    value = _number(summary.get(resolved_field))
    return {
        "value": value,
        "metric_source": {**metric_definition, "resolved": resolved_field in summary, "resolved_field": resolved_field},
        "warnings": [] if resolved_field in summary else [f"Clarity field not found: {field}"],
    }


def _resolve_action_metric(metric_definition: dict, raw_meta_row: dict) -> dict:
    action_type = metric_definition.get("action_type") or metric_definition.get("event_name")
    fallback_action_type = metric_definition.get("fallback_action_type")
    warnings = []
    value, resolved_action = _find_action(raw_meta_row, action_type, metric_definition)
    if resolved_action:
        return {
            "value": value,
            "metric_source": {**metric_definition, "resolved_action_type": resolved_action, "resolved": True},
            "warnings": [],
        }

    if fallback_action_type and metric_definition.get("fallback_policy") != "none":
        value, resolved_action = _find_action(raw_meta_row, fallback_action_type, {**metric_definition, "match_mode": "exact"})
        if resolved_action:
            return {
                "value": value,
                "metric_source": {**metric_definition, "resolved_action_type": resolved_action, "resolved": True, "used_fallback": True},
                "warnings": [f"Primary event not found: {action_type}. Used fallback: {fallback_action_type}"],
            }

    if action_type:
        warnings.append(f"Event not found: {action_type}")
    return {
        "value": 0,
        "metric_source": {**metric_definition, "resolved_action_type": None, "resolved": False},
        "warnings": warnings,
    }


def _find_action(raw_meta_row: dict, action_type: str | None, metric_definition: dict) -> tuple[float, str | None]:
    if not action_type:
        return 0, None
    target = str(action_type).casefold()
    match_mode = str(metric_definition.get("match_mode") or "exact").casefold()
    allow_generic_custom = bool(metric_definition.get("explicitly_mapped_by_gpt"))
    if target == "offsite_conversion.fb_pixel_custom" and not allow_generic_custom:
        return 0, None

    matches = []
    for item in raw_meta_row.get("actions") or []:
        current = str(item.get("action_type") or item.get("event_name") or "")
        clean_current = current.casefold()
        is_match = clean_current == target if match_mode == "exact" else target in clean_current
        if is_match:
            if clean_current == "offsite_conversion.fb_pixel_custom" and not allow_generic_custom:
                continue
            matches.append((current, _number(item.get("value"))))
    if not matches:
        return 0, None
    if metric_definition.get("fallback_mode") == "use_first_available_not_sum":
        return matches[0][1], matches[0][0]
    return sum(value for _, value in matches), matches[0][0]


def _definition_metrics(definition: dict | None) -> dict:
    metrics = dict(METRIC_DICTIONARY)
    if definition and isinstance(definition.get("metrics"), dict):
        metrics.update(definition["metrics"])
    return metrics


def _definition_stages(definition: dict | None) -> list[dict]:
    stages = (definition or {}).get("stages") or DEFAULT_DASHBOARD_DEFINITION.get("stages") or []
    return sorted(stages, key=lambda item: item.get("position", 999))


def _unmapped_custom_events(raw_meta_row: dict, metric_definitions: dict) -> list[dict]:
    explicitly_mapped = {
        str(metric.get("action_type") or metric.get("event_name") or "").casefold()
        for metric in metric_definitions.values()
        if metric.get("explicitly_mapped_by_gpt")
    }
    events = []
    for item in raw_meta_row.get("actions") or []:
        action_type = str(item.get("action_type") or "")
        clean = action_type.casefold()
        if clean == "offsite_conversion.fb_pixel_custom" and clean not in explicitly_mapped:
            events.append(
                {
                    "action_type": action_type,
                    "value": _number(item.get("value")),
                    "reason": "Not mapped by dashboard definition",
                    "status": "unmapped",
                }
            )
    return events


def _stage_status(drop: float | None, transition: float | None) -> str:
    if transition is None:
        return "neutral"
    if drop is not None and drop >= 0.8:
        return "red"
    if transition >= 0.7:
        return "green"
    if transition >= 0.35:
        return "yellow"
    return "red"


def stage_detail(stage_id: str, filters: dict | None = None) -> dict:
    if stage_id == "engaged":
        metrics = [
            {"label": "Stayed 5s", "value": 250, "source": "ga4"},
            {"label": "Stayed 10s", "value": 213, "source": "ga4"},
            {"label": "Stayed 30s", "value": 149, "source": "ga4"},
            {"label": "Stayed 60s", "value": 108, "source": "ga4"},
            {"label": "Scroll 25%", "value": 120, "source": "ga4"},
            {"label": "Scroll 50%", "value": 88, "source": "ga4"},
            {"label": "Scroll 75%", "value": 61, "source": "ga4"},
            {"label": "Scroll 100%", "value": 38, "source": "ga4"},
            {"label": "Dead Click", "value": "20%", "source": "clarity"},
            {"label": "Quickback", "value": "16.67%", "source": "clarity"},
            {"label": "Script Error", "value": "2.38%", "source": "clarity"},
        ]
        return {"stage_id": stage_id, "title": "Engagement Composition", "source": "ga4_clarity", "metrics": metrics, "filters": filters or {}}
    if stage_id == "register_page":
        metrics = [
            {"label": "Register Page Event", "value": 9, "source": "meta"},
            {"label": "Cost/Register", "value": 140.07, "source": "calculated"},
            {"label": "Transition", "value": "4.2%", "source": "calculated"},
            {"label": "Drop", "value": "95.8%", "source": "calculated"},
            {"label": "GA4 /register", "value": 9, "source": "ga4_supporting"},
        ]
        return {"stage_id": stage_id, "title": "Register Page Entry", "source": "meta_event", "metrics": metrics, "filters": filters or {}}
    funnel = build_fallback_funnel(filters)
    stage = next((item for item in funnel["stages"] if item["id"] == stage_id), funnel["stages"][0])
    return {
        "stage_id": stage["id"],
        "title": stage["label"],
        "source": stage["source"],
        "metrics": [
            {"label": "Value", "value": stage["value"], "source": stage["source"]},
            {"label": "Cost", "value": stage["cost"], "source": "calculated"},
            {"label": "Transition", "value": stage["transition_label"], "source": "calculated"},
            {"label": "Drop", "value": stage["drop_label"], "source": "calculated"},
        ],
        "filters": filters or {},
    }


def trend(stage_id: str = "register_page", metric: str = "value", days: int = 7, filters: dict | None = None) -> dict:
    today = date.today()
    points = []
    base = {"register_page": 6, "otp": 2, "complete_profile": 1, "unique_link_clicks": 80}.get(stage_id, 10)
    for index in range(days):
        current = today - timedelta(days=days - index - 1)
        points.append({"date": current.isoformat(), "value": max(0, base + ((index % 4) - 1) * 2)})
    return {
        "series": [{"entity_id": filters.get("campaign_id", "all") if filters else "all", "entity_name": "Selected scope", "points": points}],
        "stage_id": stage_id,
        "metric": metric,
    }


def comparison(entities: list[dict] | None = None, stage_id: str = "register_page", metric: str = "cost", sort: str = "lowest_cost") -> dict:
    entities = entities or [
        {"type": "campaign", "id": "120244467443630505", "name": "محادثات"},
        {"type": "adset", "id": "120248134131890505", "name": "Automation Winner Audience"},
        {"type": "ad", "id": "120248268287140505", "name": "WhatsApp AI"},
    ]
    rows = []
    for rank, entity in enumerate(entities, start=1):
        stage_value = max(1, 5 - rank)
        cost_per_stage = round(110 + rank * 24.7, 2)
        transition = round(0.08 - rank * 0.012, 3)
        rows.append(
            {
                "rank": rank,
                "entity_type": entity.get("type"),
                "entity_id": entity.get("id"),
                "entity_name": entity.get("name") or entity.get("id"),
                "stage_value": stage_value,
                "cost_per_stage": cost_per_stage,
                "transition_rate": transition,
                "drop_rate": round(1 - transition, 3),
                "strength_score": max(1, int(70 - rank * 11)),
            }
        )
    if sort == "lowest_cost":
        rows = sorted(rows, key=lambda item: item["cost_per_stage"])
    return {"rows": rows, "chart_data": {"ranking": rows, "scatter": rows}, "stage_id": stage_id, "metric": metric}


def filter_options() -> dict:
    return {
        "campaigns": [{"id": "all", "name": "All"}, {"id": "120244467443630505", "name": "محادثات"}],
        "adsets": [{"id": "all", "name": "All"}, {"id": "120248134131890505", "name": "Automation Winner Audience"}],
        "ads": [{"id": "all", "name": "All"}, {"id": "120248268287140505", "name": "WhatsApp AI"}],
        "devices": [{"id": "all", "name": "All"}, {"id": "mobile", "name": "Mobile"}, {"id": "desktop", "name": "Desktop"}],
        "placements": [{"id": "all", "name": "All"}, {"id": "facebook", "name": "Facebook"}, {"id": "instagram", "name": "Instagram"}],
        "debug": {"mode": "fallback_options"},
    }
