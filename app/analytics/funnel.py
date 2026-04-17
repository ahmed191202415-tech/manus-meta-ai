import pandas as pd
from typing import Dict, Any

from app.analytics.preprocessing import safe_div


def build_video_funnel(df: pd.DataFrame) -> Dict[str, Any]:
    if df.empty:
        return {"message": "No data found."}

    total_impressions = float(df["impressions"].sum())
    total_p50 = float(df["video_p50"].sum())
    total_p75 = float(df["video_p75"].sum())
    total_results = float(df["results"].sum())
    total_clicks = float(df["inline_link_clicks"].sum())

    return {
        "impressions": int(total_impressions),
        "video_p50": int(total_p50),
        "video_p75": int(total_p75),
        "clicks": int(total_clicks),
        "results": int(total_results),
        "p50_rate_pct": round(100 * safe_div(total_p50, total_impressions), 2),
        "p75_rate_pct": round(100 * safe_div(total_p75, total_impressions), 2),
        "result_rate_pct": round(100 * safe_div(total_results, total_impressions), 2),
        "p50_to_p75_pct": round(100 * safe_div(total_p75, total_p50), 2),
        "p75_to_click_pct": round(100 * safe_div(total_clicks, total_p75), 2),
        "click_to_result_pct": round(100 * safe_div(total_results, total_clicks), 2),
    }
