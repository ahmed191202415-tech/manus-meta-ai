import pandas as pd
from typing import Dict, Any

from app.analytics.metrics import summarize_df


def build_period_comparison(current_df: pd.DataFrame, compare_df: pd.DataFrame) -> Dict[str, Any]:
    current = summarize_df(current_df)
    previous = summarize_df(compare_df)

    keys = [
        "spend",
        "impressions",
        "clicks",
        "results",
        "ctr_pct",
        "result_rate_pct",
        "cpl",
        "p50_rate_pct",
        "p75_rate_pct",
        "click_to_result_rate_pct",
    ]

    deltas = {}
    for key in keys:
        a = current.get(key)
        b = previous.get(key)
        if a is None or b in (None, 0):
            deltas[key] = None
        else:
            deltas[key] = round(((a - b) / b) * 100, 2)

    return {
        "current": current,
        "previous": previous,
        "delta_pct": deltas,
    }
