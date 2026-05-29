import pandas as pd
import numpy as np
from typing import Dict, Any

from app.analytics.ranking import _entity_aggregates
from app.analytics.goal_context import build_goal_context


def build_decision_score(df: pd.DataFrame, level: str, top_n: int) -> Dict[str, Any]:
    if df.empty:
        return {"message": "No data found."}

    goal_context = build_goal_context(df)
    primary_goal = goal_context.get("primary_goal")
    grouped = _entity_aggregates(df, level)

    spend_norm = grouped["spend"] / grouped["spend"].max() if grouped["spend"].max() else 0
    result_rate_norm = grouped["result_rate_pct"].fillna(0) / max(grouped["result_rate_pct"].fillna(0).max(), 1)
    p75_norm = grouped["p75_rate_pct"].fillna(0) / max(grouped["p75_rate_pct"].fillna(0).max(), 1)
    cpl_series = grouped["cpl"].fillna(grouped["cpl"].max() if grouped["cpl"].notna().any() else 0)
    cpl_norm = 1 - (cpl_series / max(cpl_series.max(), 1))

    grouped["decision_score"] = (spend_norm * 10) + (result_rate_norm * 40) + (p75_norm * 20) + (cpl_norm * 30)

    def decide(row: pd.Series) -> str:
        if row["decision_score"] >= 70 and row["results"] >= 3:
            return "SCALE"
        if row["decision_score"] >= 45:
            return "HOLD / KEEP TESTING"
        if primary_goal in {"messages", "traffic", "awareness_engagement"}:
            return "HOLD / CHECK GOAL FIT"
        return "KILL OR REBUILD"

    grouped["decision"] = grouped.apply(decide, axis=1)
    grouped["decision_guardrail"] = goal_context.get("warning") or ""
    grouped = grouped.sort_values(["decision_score", "results"], ascending=[False, False])

    cols = [
        f"{level}_id",
        f"{level}_name",
        "spend",
        "results",
        "result_rate_pct",
        "cpl",
        "p75_rate_pct",
        "decision_score",
        "decision",
        "decision_guardrail",
    ]

    return {
        "goal_context": goal_context,
        "entities": grouped.head(top_n)[cols].round(2).replace({np.nan: None}).to_dict(orient="records")
    }


def build_scale_kill_hold(df: pd.DataFrame, level: str, top_n: int) -> Dict[str, Any]:
    scored = build_decision_score(df, level, max(top_n, 20))
    entities = pd.DataFrame(scored.get("entities", []))

    if entities.empty:
        return {"message": "No data found."}

    return {
        "goal_context": scored.get("goal_context"),
        "scale": entities[entities["decision"] == "SCALE"].head(top_n).to_dict(orient="records"),
        "hold": entities[entities["decision"] == "HOLD / KEEP TESTING"].head(top_n).to_dict(orient="records"),
        "check_goal_fit": entities[entities["decision"] == "HOLD / CHECK GOAL FIT"].head(top_n).to_dict(orient="records"),
        "kill": entities[entities["decision"] == "KILL OR REBUILD"].head(top_n).to_dict(orient="records"),
    }


def build_budget_reallocation(df: pd.DataFrame, level: str, top_n: int) -> Dict[str, Any]:
    scored = build_decision_score(df, level, 100)
    entities = pd.DataFrame(scored.get("entities", []))

    if entities.empty:
        return {"message": "No data found."}

    total_spend = float(entities["spend"].sum()) if "spend" in entities.columns else 0.0
    scale = entities[entities["decision"] == "SCALE"].copy()
    kill = entities[entities["decision"] == "KILL OR REBUILD"].copy()

    if scale.empty:
        return {"message": "No scalable entities identified for budget reallocation."}

    scale["suggested_extra_budget_share_pct"] = round(100 / len(scale), 2)
    released = float(kill["spend"].sum()) if not kill.empty else 0.0

    return {
        "goal_context": scored.get("goal_context"),
        "released_budget_estimate": round(released, 2),
        "scale_targets": scale.head(top_n).replace({np.nan: None}).to_dict(orient="records"),
        "stop_targets": kill.head(top_n).replace({np.nan: None}).to_dict(orient="records"),
        "portfolio_spend": round(total_spend, 2),
    }
