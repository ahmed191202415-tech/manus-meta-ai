from __future__ import annotations

from typing import Any

import pandas as pd

from app.analytics.goal_context import build_goal_context
from app.analytics.intelligent_diagnostics import build_intelligence_diagnostics
from app.analytics.meta_delivery_context import relevant_entity_ids, summarize_delivery_context
from app.analytics.semantic_metrics import aggregate_metrics
from app.analytics.statistics_engine import pct_change


CAUSAL_GRAPH = [
    {"from": "spend", "to": "impressions", "mechanism": "budget_delivery"},
    {"from": "cpm", "to": "impressions", "mechanism": "auction_cost"},
    {"from": "frequency", "to": "ctr", "mechanism": "audience_fatigue"},
    {"from": "ctr", "to": "outbound_clicks", "mechanism": "creative_interest"},
    {"from": "outbound_clicks", "to": "landing_page_views", "mechanism": "page_load_and_redirect"},
    {"from": "landing_page_views", "to": "conversion", "mechanism": "offer_and_page_quality"},
    {"from": "tracking_quality", "to": "reported_conversion", "mechanism": "measurement_integrity"},
]


def build_professional_analyst_brief(
    current_df: pd.DataFrame | list[dict],
    compare_df: pd.DataFrame | list[dict] | None,
    level: str,
    adsets: list[dict] | None = None,
    diagnostics: dict | None = None,
) -> dict:
    current_df = pd.DataFrame(current_df) if isinstance(current_df, list) else current_df
    compare_df = pd.DataFrame(compare_df) if isinstance(compare_df, list) else compare_df
    campaign_ids, adset_ids = relevant_entity_ids(current_df)
    delivery = summarize_delivery_context(adsets, campaign_ids=campaign_ids, adset_ids=adset_ids)
    goal = build_goal_context(current_df, delivery)
    diagnostic_result = diagnostics or build_intelligence_diagnostics(
        current_df,
        compare_df if compare_df is not None else pd.DataFrame(),
        level,
        10,
    )
    top_diagnostics = diagnostic_result.get("top_diagnostics", [])
    aggregate = _aggregate_first(current_df, level)
    previous = _aggregate_first(compare_df, level)
    changes = _metric_changes(aggregate, previous)
    root_causes = [_root_cause(item) for item in top_diagnostics[:5]]
    confidence = _confidence(current_df, delivery, top_diagnostics)

    return {
        "analyst_mode": "professional_marketing_data_analyst",
        "goal_context": goal,
        "delivery_context": delivery,
        "root_cause_graph": CAUSAL_GRAPH,
        "ranked_root_causes": root_causes,
        "metric_changes": changes,
        "assumptions": _assumptions(goal, delivery),
        "answer_contract": _answer_contract(goal, confidence),
        "confidence": confidence,
        "analyst_summary": _summary(goal, root_causes, confidence),
    }


def _aggregate_first(df: pd.DataFrame | None, level: str) -> dict:
    if df is None or df.empty:
        return {}
    grouped = aggregate_metrics(df, level)
    if grouped.empty:
        return {}
    numeric = grouped.select_dtypes(include="number").sum().to_dict()
    return {key: round(float(value), 6) for key, value in numeric.items()}


def _metric_changes(current: dict, previous: dict) -> dict:
    keys = ["spend", "cpm", "ctr", "frequency", "outbound_clicks_count", "landing_page_views", "purchases", "leads", "messaging_conversations", "cpa_purchase", "roas_calc"]
    return {key: pct_change(current.get(key), previous.get(key)) for key in keys if key in current}


def _root_cause(hit: dict) -> dict:
    scenario = hit.get("scenario")
    chain_map = {
        "Creative Fatigue": ["frequency_up", "ctr_down", "cpm_or_cpa_up", "performance_pressure"],
        "Audience Saturation": ["audience_repetition", "ctr_down", "delivery_efficiency_down"],
        "Landing Page Friction": ["outbound_click", "landing_page_view_loss", "page_speed_redirect_or_tracking_issue"],
        "Offer / Product Friction": ["landing_page_view", "weak_add_to_cart_or_intent", "offer_or_message_match_issue"],
        "Checkout Friction": ["add_to_cart", "checkout_or_purchase_loss", "checkout_trust_payment_issue"],
        "Budget Waste": ["spend_up", "incremental_results_flat", "cpa_up", "scaling_blocked"],
        "Auction Pressure": ["cpm_up", "ctr_down", "auction_or_relevance_pressure"],
        "Weak Signal Quality": ["clicks_present", "conversion_signal_weak", "tracking_or_traffic_quality_issue"],
        "Weak Hook / Thumbstop Problem": ["impressions", "weak_thumbstop", "creative_hook_issue"],
        "Video Hold / Message Continuity Problem": ["video_start", "retention_drop", "message_continuity_issue"],
    }
    return {
        "rank_score": hit.get("score"),
        "severity": hit.get("severity"),
        "scenario": scenario,
        "entity": {"level": hit.get("entity_level"), "id": hit.get("entity_id"), "name": hit.get("entity_name")},
        "causal_chain": chain_map.get(scenario, ["observed_signal", "probable_performance_effect"]),
        "evidence": hit.get("evidence", {}),
        "recommended_action": hit.get("recommended_action_ar"),
    }


def _confidence(df: pd.DataFrame, delivery: dict, hits: list[dict]) -> str:
    rows = len(df) if df is not None else 0
    if rows == 0:
        return "low"
    if delivery.get("primary_optimization_goal") and hits:
        return "high"
    if hits or delivery.get("primary_optimization_goal"):
        return "medium"
    return "low"


def _assumptions(goal: dict, delivery: dict) -> list[dict]:
    assumptions = []
    if not delivery.get("primary_optimization_goal"):
        assumptions.append({"assumption": "adset_optimization_goal_missing", "impact": "Use campaign objective and observed actions with lower confidence."})
    if goal.get("primary_goal") == "messages":
        assumptions.append({"assumption": "message_quality_not_available", "impact": "Conversation quality and closed sales require CRM or inbox data."})
    if goal.get("primary_goal") == "sales":
        assumptions.append({"assumption": "reported_purchase_tracking_is_valid", "impact": "Validate Pixel/CAPI when Meta and GA4 disagree."})
    return assumptions


def _answer_contract(goal: dict, confidence: str) -> dict:
    return {
        "internal_instruction": "Use the detected objective silently. Do not over-explain objective detection unless the user asks.",
        "required_answer_order": ["executive_judgement", "strongest_evidence", "ranked_root_causes", "next_actions", "confidence_and_limits"],
        "must_use_primary_metrics": goal.get("primary_success_metrics", []),
        "avoid": [
            "Do not judge a messages campaign mainly by purchases or website leads.",
            "Do not judge an awareness or traffic campaign mainly by CPA.",
            "Do not claim causation when evidence only supports a probable root cause.",
        ],
        "confidence": confidence,
    }


def _summary(goal: dict, root_causes: list[dict], confidence: str) -> str:
    primary = goal.get("primary_goal", "unknown")
    if root_causes:
        return f"Analyze as {primary}. Highest-priority issue: {root_causes[0].get('scenario')}. Confidence: {confidence}."
    return f"Analyze as {primary}. No strong root-cause signal was detected yet. Confidence: {confidence}."
