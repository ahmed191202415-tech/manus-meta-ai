import pandas as pd
import numpy as np
from typing import Dict, Any


def _entity_aggregates(df: pd.DataFrame, level: str) -> pd.DataFrame:
    grouped = df.groupby([f"{level}_id", f"{level}_name"], dropna=False).agg({
        "spend": "sum",
        "impressions": "sum",
        "inline_link_clicks": "sum",
        "results": "sum",
        "video_p50": "sum",
        "video_p75": "sum",
    }).reset_index()

    grouped["ctr_pct"] = 100 * grouped["inline_link_clicks"] / grouped["impressions"].replace(0, np.nan)
    grouped["result_rate_pct"] = 100 * grouped["results"] / grouped["impressions"].replace(0, np.nan)
    grouped["cpl"] = grouped["spend"] / grouped["results"].replace(0, np.nan)
    grouped["p75_rate_pct"] = 100 * grouped["video_p75"] / grouped["impressions"].replace(0, np.nan)
    grouped["click_to_result_rate_pct"] = 100 * grouped["results"] / grouped["inline_link_clicks"].replace(0, np.nan)
    return grouped


def build_ranking(df: pd.DataFrame, level: str, top_n: int) -> Dict[str, Any]:
    if df.empty:
        return {"message": "No data found."}

    grouped = _entity_aggregates(df, level)

    result_rate_norm = grouped["result_rate_pct"].fillna(0)
    p75_norm = grouped["p75_rate_pct"].fillna(0)
    results_norm = grouped["results"].fillna(0)
    cpl_penalty = grouped["cpl"].fillna(grouped["cpl"].max() if grouped["cpl"].notna().any() else 0)

    grouped["score"] = (result_rate_norm * 4) + (p75_norm * 2) + (results_norm * 0.2) - (cpl_penalty * 0.2)
    grouped = grouped.sort_values(["score", "results"], ascending=[False, False])

    cols = [
        f"{level}_id",
        f"{level}_name",
        "spend",
        "impressions",
        "inline_link_clicks",
        "results",
        "ctr_pct",
        "result_rate_pct",
        "click_to_result_rate_pct",
        "cpl",
        "p75_rate_pct",
        "score",
    ]

    return {
        "top": grouped.head(top_n)[cols].round(2).replace({np.nan: None}).to_dict(orient="records"),
        "bottom": grouped.tail(top_n)[cols].round(2).replace({np.nan: None}).to_dict(orient="records"),
    }
