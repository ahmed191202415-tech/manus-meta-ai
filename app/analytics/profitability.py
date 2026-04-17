
import pandas as pd
from typing import Dict, Any, Optional


def build_break_even_analysis(
    df: pd.DataFrame,
    break_even_cpl: Optional[float] = None,
    revenue_per_result: Optional[float] = None,
    gross_margin_pct: Optional[float] = None,
) -> Dict[str, Any]:
    if df.empty:
        return {"message": "No data found."}

    spend = float(df["spend"].sum()) if "spend" in df.columns else 0.0
    results = float(df["results"].sum()) if "results" in df.columns else 0.0
    cpl = (spend / results) if results > 0 else None

    inferred_break_even_cpl = None
    if break_even_cpl is not None:
        inferred_break_even_cpl = float(break_even_cpl)
    elif revenue_per_result is not None and gross_margin_pct is not None:
        inferred_break_even_cpl = float(revenue_per_result) * (float(gross_margin_pct) / 100.0)

    gap = None
    status = "UNKNOWN"
    if cpl is not None and inferred_break_even_cpl is not None:
        gap = round(cpl - inferred_break_even_cpl, 2)
        if cpl < inferred_break_even_cpl:
            status = "PROFITABLE"
        elif cpl == inferred_break_even_cpl:
            status = "BREAK-EVEN"
        else:
            status = "UNPROFITABLE"

    return {
        "spend": round(spend, 2),
        "results": round(results, 2),
        "actual_cpl": round(cpl, 2) if cpl is not None else None,
        "break_even_cpl": round(inferred_break_even_cpl, 2) if inferred_break_even_cpl is not None else None,
        "gap_vs_break_even": gap,
        "status": status,
    }
