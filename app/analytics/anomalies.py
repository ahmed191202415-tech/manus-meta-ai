import pandas as pd
import numpy as np
from scipy import stats
from typing import Dict, Any


def build_anomaly_scan(df: pd.DataFrame, level: str) -> Dict[str, Any]:
    if df.empty or "date_start" not in df.columns:
        return {"message": "Not enough data for anomaly scan."}

    grp = df.groupby(["date_start", f"{level}_name"], dropna=False).agg({
        "results": "sum",
        "spend": "sum",
        "impressions": "sum",
    }).reset_index()

    if len(grp) < 4:
        return {"message": "Not enough data points for anomaly scan."}

    grp["result_rate"] = grp["results"] / grp["impressions"].replace(0, np.nan)
    metric = grp["result_rate"].fillna(0)
    z = np.abs(stats.zscore(metric, nan_policy="omit")) if len(metric) > 2 else np.zeros(len(metric))
    grp["z_score"] = np.nan_to_num(z)
    anomalies = grp[grp["z_score"] >= 2.0].sort_values("z_score", ascending=False)

    return {
        "anomalies": anomalies.head(20).round(4).replace({np.nan: None}).to_dict(orient="records")
    }
