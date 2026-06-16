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
    "unique_link_clicks": {"source": "meta", "field": "unique_link_clicks"},
    "landing_loaded": {"source": "ga4", "event_name": "Window Loaded"},
    "stayed_10s": {"source": "ga4", "event_name": "landing_stayed_10s"},
    "scroll_50": {"source": "ga4", "event_name": "Scroll - BeOn Landing 50"},
    "quickback": {"source": "clarity", "field": "quickback"},
    "dead_click": {"source": "clarity", "field": "dead_click"},
    "script_error": {"source": "clarity", "field": "script_error"},
    "register_page": {"source": "meta_event", "event_name": "Register Page"},
    "otp": {"source": "meta_event", "event_name": "OTP"},
    "complete_profile": {"source": "meta_event", "event_name": "Complete Profile"},
    "start_trial": {"source": "meta_event", "event_name": "Start Trial"},
    "complete_registration": {"source": "meta_event", "event_name": "CompleteRegistration"},
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
    metrics = _metrics_for_query(query_id)
    calls = []
    for metric in metrics:
        meta = METRIC_DICTIONARY.get(metric, {})
        source = meta.get("source")
        if source in {"meta", "meta_event"}:
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


def _metrics_for_query(query_id: str | None) -> list[str]:
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
            "message": "Live connector data was not required for this preview response.",
            "query_plan": build_query_plan(DEFAULT_DASHBOARD_DEFINITION, "journey_funnel"),
        },
    }


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
