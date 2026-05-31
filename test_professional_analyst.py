import pandas as pd

from app.analytics.goal_context import build_goal_context
from app.analytics.intelligent_diagnostics import build_intelligence_diagnostics
from app.analytics.meta_delivery_context import attach_delivery_context, summarize_delivery_context
from app.analytics.professional_analyst import build_professional_analyst_brief
from app.analytics.semantic_metrics import aggregate_metrics


def _sales_campaign_messages_adset():
    rows = [
        {
            "campaign_id": "c1",
            "campaign_name": "Sales with WhatsApp",
            "adset_id": "s1",
            "adset_name": "Messages",
            "objective": "OUTCOME_SALES",
            "spend": 120,
            "impressions": 1000,
            "inline_link_clicks": 40,
            "actions": [
                {"action_type": "messaging_conversation_started_7d", "value": "8"},
                {"action_type": "purchase", "value": "1"},
            ],
        }
    ]
    adsets = [{"id": "s1", "name": "Messages", "campaign_id": "c1", "optimization_goal": "CONVERSATIONS", "billing_event": "IMPRESSIONS"}]
    return rows, adsets


def test_adset_optimization_goal_overrides_campaign_sales_objective():
    rows, adsets = _sales_campaign_messages_adset()
    delivery = summarize_delivery_context(adsets, campaign_ids={"c1"}, adset_ids={"s1"})
    context = build_goal_context(rows, delivery)

    assert context["campaign_goal"] == "sales"
    assert context["adset_optimization_goal"] == "CONVERSATIONS"
    assert context["primary_goal"] == "messages"
    assert context["source"] == "adset_optimization_goal"


def test_delivery_context_recomputes_results_using_adset_optimization():
    rows, adsets = _sales_campaign_messages_adset()
    frame = attach_delivery_context(pd.DataFrame(rows), adsets)

    assert frame.loc[0, "results"] == 8
    assert frame.loc[0, "result_action_type"] == "messaging_conversation_started_7d"


def test_professional_analyst_brief_contains_answer_contract():
    rows, adsets = _sales_campaign_messages_adset()
    frame = attach_delivery_context(pd.DataFrame(rows), adsets)
    brief = build_professional_analyst_brief(frame, None, "adset", adsets=adsets)

    assert brief["goal_context"]["primary_goal"] == "messages"
    assert brief["answer_contract"]["required_answer_order"][0] == "executive_judgement"
    assert brief["root_cause_graph"]


def test_semantic_aggregation_preserves_funnel_metrics():
    df = pd.DataFrame(
        [
            {
                "ad_id": "a1",
                "ad_name": "Creative",
                "spend": 100,
                "impressions": 1000,
                "inline_link_clicks": 50,
                "outbound_clicks": [{"action_type": "outbound_click", "value": "40"}],
                "actions": [
                    {"action_type": "landing_page_view", "value": "20"},
                    {"action_type": "add_to_cart", "value": "3"},
                ],
            }
        ]
    )

    grouped = aggregate_metrics(df, "ad")

    assert grouped.loc[0, "outbound_clicks_count"] == 40
    assert grouped.loc[0, "landing_page_views"] == 20
    assert grouped.loc[0, "add_to_cart"] == 3


def test_messages_optimization_does_not_emit_purchase_funnel_diagnosis():
    rows, adsets = _sales_campaign_messages_adset()
    rows[0]["actions"].extend(
        [
            {"action_type": "landing_page_view", "value": "30"},
            {"action_type": "add_to_cart", "value": "6"},
        ]
    )
    frame = attach_delivery_context(pd.DataFrame(rows), adsets)
    result = build_intelligence_diagnostics(frame, pd.DataFrame(), "adset", 20)
    scenarios = {item["scenario"] for item in result["top_diagnostics"]}

    assert "Checkout Friction" not in scenarios
    assert "Offer / Product Friction" not in scenarios
