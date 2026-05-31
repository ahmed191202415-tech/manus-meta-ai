from __future__ import annotations

from collections import Counter
from typing import Any

import pandas as pd


MESSAGE_ACTIONS = {
    "messaging_conversation_started_7d",
    "onsite_conversion.messaging_conversation_started_7d",
    "onsite_conversion.messaging_first_reply",
    "onsite_conversion.messaging_conversation_replied_7d",
    "contact",
}
LEAD_ACTIONS = {
    "lead",
    "onsite_conversion.lead_grouped",
    "offsite_complete_registration_add_meta_leads",
    "submit_application",
    "complete_registration",
}
PURCHASE_ACTIONS = {
    "purchase",
    "omni_purchase",
    "onsite_conversion.purchase",
    "offsite_conversion.fb_pixel_purchase",
}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _action_counts(rows: list[Any]) -> Counter:
    counts: Counter = Counter()
    for actions in rows:
        if not isinstance(actions, list):
            continue
        for item in actions:
            if not isinstance(item, dict):
                continue
            action_type = _clean(item.get("action_type"))
            if not action_type:
                continue
            try:
                value = float(item.get("value") or 0)
            except (TypeError, ValueError):
                value = 0.0
            counts[action_type] += value
    return counts


def _classify_objective(objective: str) -> str | None:
    value = objective.lower()
    if "message" in value or "whatsapp" in value or "conversation" in value:
        return "messages"
    if "lead" in value:
        return "leads"
    if "sales" in value or "conversion" in value or "purchase" in value or "catalog" in value:
        return "sales"
    if "traffic" in value or "link_click" in value or "landing" in value:
        return "traffic"
    if "awareness" in value or "reach" in value or "video" in value or "engagement" in value:
        return "awareness_engagement"
    return None


def _classify_actions(counts: Counter) -> str | None:
    message_total = sum(counts.get(action, 0) for action in MESSAGE_ACTIONS)
    lead_total = sum(counts.get(action, 0) for action in LEAD_ACTIONS)
    purchase_total = sum(counts.get(action, 0) for action in PURCHASE_ACTIONS)
    if message_total >= max(lead_total, purchase_total, 1):
        return "messages"
    if lead_total >= max(message_total, purchase_total, 1):
        return "leads"
    if purchase_total >= max(message_total, lead_total, 1):
        return "sales"
    return None


def build_goal_context(df: pd.DataFrame | list[dict] | None, delivery_context: dict | None = None) -> dict:
    if df is None:
        return _unknown_context()
    frame = pd.DataFrame(df) if isinstance(df, list) else df
    if frame is None or frame.empty:
        return _unknown_context()

    objective_counts = Counter()
    objective_goals = Counter()
    if "objective" in frame.columns:
        for objective in frame["objective"].dropna().tolist():
            objective_text = _clean(objective)
            if not objective_text:
                continue
            objective_counts[objective_text] += 1
            classified = _classify_objective(objective_text)
            if classified:
                objective_goals[classified] += 1

    actions = frame["actions"].tolist() if "actions" in frame.columns else []
    action_counts = _action_counts(actions)
    action_goal = _classify_actions(action_counts)

    primary_goal = None
    source = "unknown"
    if objective_goals:
        primary_goal = objective_goals.most_common(1)[0][0]
        source = "campaign_objective"
    elif action_goal:
        primary_goal = action_goal
        source = "observed_actions"

    optimization_goal = _clean((delivery_context or {}).get("primary_optimization_goal"))
    optimization_class = _classify_objective(optimization_goal) if optimization_goal else None
    if optimization_class:
        primary_goal = optimization_class
        source = "adset_optimization_goal"

    if not primary_goal:
        return _unknown_context(objective_counts, action_counts)

    result_label_map = {
        "messages": "messaging_conversations",
        "leads": "leads",
        "sales": "purchases_or_revenue",
        "traffic": "landing_page_views_or_click_quality",
        "awareness_engagement": "reach_frequency_video_or_engagement",
    }
    primary_metric_map = {
        "messages": ["messaging_conversation_started_7d", "cost_per_messaging_conversation", "reply_quality"],
        "leads": ["lead", "cost_per_lead", "lead_quality"],
        "sales": ["purchase", "roas", "cost_per_purchase", "revenue"],
        "traffic": ["landing_page_views", "outbound_clicks", "click_to_landing_page_view_rate"],
        "awareness_engagement": ["reach", "frequency", "thruplay", "engagement_rate"],
    }
    analysis_guardrails = {
        "messages": [
            "Do not judge this as a lead/sales campaign unless lead or purchase tracking is explicitly present.",
            "Prioritize conversation starts, reply rate, response quality, and downstream manual sales follow-up.",
        ],
        "leads": [
            "Judge lead volume, CPL, and lead quality; purchases may be a later-stage metric.",
        ],
        "sales": [
            "Judge purchase/revenue/ROAS first, then diagnose click and landing-page leakage.",
        ],
        "traffic": [
            "Judge click quality and landing-page arrival before lead or purchase conversion.",
        ],
        "awareness_engagement": [
            "Do not force CPA decisions; judge reach, frequency, video retention, and engagement quality.",
        ],
    }

    return {
        "primary_goal": primary_goal,
        "source": source,
        "campaign_goal": objective_goals.most_common(1)[0][0] if objective_goals else None,
        "adset_optimization_goal": optimization_goal or None,
        "adset_optimization_class": optimization_class,
        "result_label": result_label_map[primary_goal],
        "primary_success_metrics": primary_metric_map[primary_goal],
        "detected_objectives": dict(objective_counts.most_common(8)),
        "top_action_types": dict(action_counts.most_common(10)),
        "analysis_guardrails": analysis_guardrails[primary_goal],
        "warning": _warning(primary_goal),
    }


def _unknown_context(objective_counts: Counter | None = None, action_counts: Counter | None = None) -> dict:
    return {
        "primary_goal": "unknown",
        "source": "missing_objective_and_actions",
        "result_label": "results",
        "primary_success_metrics": ["results", "cost_per_result", "click_quality"],
        "detected_objectives": dict((objective_counts or Counter()).most_common(8)),
        "top_action_types": dict((action_counts or Counter()).most_common(10)),
        "analysis_guardrails": [
            "Objective was not available; avoid strong Scale/Hold/Stop decisions until campaign/adset objective is fetched.",
        ],
        "warning": "Campaign goal is unknown, so results may mix messages, leads, purchases, and traffic actions.",
    }


def _warning(goal: str) -> str:
    if goal == "messages":
        return "This looks like a messages campaign; do not treat missing leads or purchases as failure by itself."
    if goal == "traffic":
        return "This looks like a traffic campaign; conversion analysis needs website events before judging sales quality."
    if goal == "awareness_engagement":
        return "This looks like an awareness/engagement campaign; CPA-style decisions may be misleading."
    return ""
