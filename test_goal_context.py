import pandas as pd

from app.analytics.decisions import build_decision_score
from app.analytics.goal_context import build_goal_context
from app.analytics.preprocessing import frame_from_insights


def test_goal_context_detects_messages_from_objective_and_actions():
    rows = [
        {
            "campaign_id": "1",
            "campaign_name": "Messages test",
            "objective": "OUTCOME_MESSAGES",
            "actions": [{"action_type": "messaging_conversation_started_7d", "value": "12"}],
        }
    ]

    context = build_goal_context(rows)

    assert context["primary_goal"] == "messages"
    assert context["result_label"] == "messaging_conversations"
    assert "leads or purchases" in context["warning"]


def test_goal_context_detects_leads_from_actions_without_objective():
    context = build_goal_context(
        [
            {
                "actions": [
                    {"action_type": "lead", "value": "4"},
                    {"action_type": "purchase", "value": "1"},
                ]
            }
        ]
    )

    assert context["primary_goal"] == "leads"


def test_frame_results_follow_objective_before_other_action_types():
    rows = [
        {
            "campaign_id": "1",
            "campaign_name": "Messages campaign",
            "objective": "OUTCOME_MESSAGES",
            "spend": "100",
            "impressions": "1000",
            "inline_link_clicks": "50",
            "actions": [
                {"action_type": "messaging_conversation_started_7d", "value": "6"},
                {"action_type": "purchase", "value": "20"},
            ],
        }
    ]

    df = frame_from_insights(rows, "campaign")

    assert df.loc[0, "results"] == 6
    assert df.loc[0, "result_action_type"] == "messaging_conversation_started_7d"


def test_message_campaign_low_score_is_not_kill_decision():
    df = pd.DataFrame(
        [
            {
                "campaign_id": "1",
                "campaign_name": "Messages weak test",
                "objective": "OUTCOME_MESSAGES",
                "spend": 100.0,
                "impressions": 1000.0,
                "inline_link_clicks": 5.0,
                "results": 0.0,
                "cpl": None,
                "video_p50": 0.0,
                "video_p75": 0.0,
                "p75_rate_pct": 0.0,
                "result_rate_pct": 0.0,
            }
        ]
    )

    result = build_decision_score(df, "campaign", 5)

    assert result["goal_context"]["primary_goal"] == "messages"
    assert result["entities"][0]["decision"] == "HOLD / CHECK GOAL FIT"
