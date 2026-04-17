import pandas as pd
from typing import Dict, Any

from app.analytics.preprocessing import safe_div


def summarize_df(df: pd.DataFrame) -> Dict[str, Any]:
    if df.empty:
        return {"message": "No data found."}

    total_spend = float(df["spend"].sum())
    total_impressions = float(df["impressions"].sum())
    total_clicks = float(df["inline_link_clicks"].sum())
    total_results = float(df["results"].sum())
    total_p50 = float(df["video_p50"].sum())
    total_p75 = float(df["video_p75"].sum())

    return {
        "spend": round(total_spend, 2),
        "impressions": int(total_impressions),
        "clicks": int(total_clicks),
        "results": int(total_results),
        "ctr_pct": round(100 * safe_div(total_clicks, total_impressions), 2),
        "result_rate_pct": round(100 * safe_div(total_results, total_impressions), 2),
        "cpl": round(safe_div(total_spend, total_results), 2) if total_results else None,
        "p50_rate_pct": round(100 * safe_div(total_p50, total_impressions), 2),
        "p75_rate_pct": round(100 * safe_div(total_p75, total_impressions), 2),
        "click_to_result_rate_pct": round(100 * safe_div(total_results, total_clicks), 2),
    }
