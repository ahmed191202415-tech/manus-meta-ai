import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score
from typing import Dict, Any

from app.analytics.ranking import _entity_aggregates


def build_forecast(df: pd.DataFrame, horizon_days: int = 7) -> Dict[str, Any]:
    if df.empty or "date_start" not in df.columns:
        return {"message": "No daily data available for forecasting."}

    daily = df.groupby("date_start").agg({
        "spend": "sum",
        "results": "sum",
        "impressions": "sum",
        "inline_link_clicks": "sum",
    }).reset_index().sort_values("date_start")

    if len(daily) < 4:
        return {"message": "Not enough daily points for forecasting."}

    daily["day_index"] = np.arange(len(daily))
    forecasts: Dict[str, Any] = {
        "history": daily.replace({np.nan: None}).to_dict(orient="records"),
        "forecast": {},
    }

    for metric in ["spend", "results", "impressions", "inline_link_clicks"]:
        model = LinearRegression()
        X = daily[["day_index"]].values
        y = daily[metric].values
        model.fit(X, y)

        future_idx = np.arange(len(daily), len(daily) + horizon_days).reshape(-1, 1)
        preds = np.maximum(model.predict(future_idx), 0)

        forecasts["forecast"][metric] = [round(float(x), 2) for x in preds]
        forecasts.setdefault("model_fit", {})[metric] = round(float(r2_score(y, model.predict(X))), 4)

    return forecasts


def build_prediction(df: pd.DataFrame, level: str, top_n: int) -> Dict[str, Any]:
    if df.empty:
        return {"message": "No data found."}

    grouped = _entity_aggregates(df, level)
    usable = grouped.dropna(subset=["cpl"]).copy()

    if len(usable) < 4:
        return {"message": "Not enough entities for predictive scoring."}

    features = usable[["spend", "impressions", "inline_link_clicks", "p75_rate_pct"]].fillna(0)
    target = usable["results"].fillna(0)

    model = LinearRegression()
    model.fit(features, target)

    usable["predicted_results_next_cycle"] = np.maximum(model.predict(features), 0)
    usable["predicted_cpl_next_cycle"] = np.where(
        usable["predicted_results_next_cycle"] > 0,
        usable["spend"] / usable["predicted_results_next_cycle"],
        np.nan
    )

    usable = usable.sort_values("predicted_results_next_cycle", ascending=False)

    return {
        "prediction_quality": {"r2": round(float(model.score(features, target)), 4)},
        "entities": usable.head(top_n)[[
            f"{level}_id",
            f"{level}_name",
            "results",
            "predicted_results_next_cycle",
            "cpl",
            "predicted_cpl_next_cycle",
            "p75_rate_pct",
        ]].round(2).replace({np.nan: None}).to_dict(orient="records")
    }
