import pandas as pd
from typing import Dict, Any, Optional

from app.analytics.metrics import summarize_df
from app.analytics.ranking import build_ranking
from app.analytics.funnel import build_video_funnel
from app.analytics.diagnostics import build_drop_reason
from app.analytics.decisions import build_scale_kill_hold
from app.analytics.prediction import build_forecast
from app.analytics.goal_context import build_goal_context


def build_executive_report(current_df: pd.DataFrame, compare_df: Optional[pd.DataFrame], level: str, top_n: int) -> Dict[str, Any]:
    summary = summarize_df(current_df)
    goal_context = build_goal_context(current_df)
    ranking = build_ranking(current_df, level, min(top_n, 5))
    funnel = build_video_funnel(current_df)
    drop = build_drop_reason(current_df, compare_df) if compare_df is not None and not compare_df.empty else None
    decisions = build_scale_kill_hold(current_df, level, 5)
    forecast = build_forecast(current_df, 7)

    bullets = [
        f"إجمالي الإنفاق: {summary.get('spend')}",
        f"إجمالي النتائج: {summary.get('results')}",
        f"CTR: {summary.get('ctr_pct')}%",
        f"Result Rate: {summary.get('result_rate_pct')}%",
        f"P75 Rate: {summary.get('p75_rate_pct')}%",
    ]

    if drop:
        bullets.extend(drop.get("suspected_reasons", []))

    return {
        "goal_context": goal_context,
        "summary": summary,
        "top_entities": ranking.get("top", []),
        "bottom_entities": ranking.get("bottom", []),
        "video_funnel": funnel,
        "decisions": decisions,
        "forecast": forecast,
        "recommendations": bullets,
    }
