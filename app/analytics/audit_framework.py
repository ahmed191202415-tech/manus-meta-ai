
import pandas as pd
from typing import Dict, Any

from app.analytics.metrics import summarize_df
from app.analytics.ranking import build_ranking
from app.analytics.funnel import build_video_funnel
from app.analytics.diagnostics import build_deep_root_cause


def build_audit_snapshot(current_df: pd.DataFrame, compare_df: pd.DataFrame, level: str) -> Dict[str, Any]:
    if current_df.empty:
        return {"message": "No data found."}

    summary = summarize_df(current_df)
    ranking = build_ranking(current_df, level, 5)
    funnel = build_video_funnel(current_df)

    root_cause = None
    if compare_df is not None and not compare_df.empty:
        root_cause = build_deep_root_cause(current_df, compare_df)

    findings = []

    cpl = summary.get("cpl")
    ctr = summary.get("ctr_pct")
    result_rate = summary.get("result_rate_pct")
    p75 = summary.get("p75_rate_pct")

    if cpl is not None and cpl > 0:
        findings.append(f"CPL الحالي: {cpl}")
    if ctr is not None:
        findings.append(f"CTR الحالي: {ctr}%")
    if result_rate is not None:
        findings.append(f"Result Rate الحالي: {result_rate}%")
    if p75 is not None:
        findings.append(f"P75 الحالي: {p75}%")

    return {
        "summary": summary,
        "top_entities": ranking.get("top", []),
        "bottom_entities": ranking.get("bottom", []),
        "funnel": funnel,
        "root_cause": root_cause,
        "findings": findings,
    }
