import pandas as pd
import numpy as np
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from typing import Dict, Any

from app.analytics.ranking import _entity_aggregates


def build_clustering(df: pd.DataFrame, level: str, n_clusters: int = 3) -> Dict[str, Any]:
    if df.empty:
        return {"message": "No data found."}

    grouped = _entity_aggregates(df, level)
    features = grouped[["ctr_pct", "result_rate_pct", "cpl", "p75_rate_pct"]].replace([np.inf, -np.inf], np.nan).fillna(0)

    if len(features) < n_clusters:
        return {"message": "Not enough entities for clustering."}

    scaled = StandardScaler().fit_transform(features)
    model = KMeans(n_clusters=n_clusters, n_init=10, random_state=42)
    grouped["cluster"] = model.fit_predict(scaled)

    summary = grouped.groupby("cluster").agg({
        "ctr_pct": "mean",
        "result_rate_pct": "mean",
        "cpl": "mean",
        "p75_rate_pct": "mean",
        "results": "sum",
    }).reset_index().round(2)

    return {
        "clusters": summary.replace({np.nan: None}).to_dict(orient="records"),
        "entities": grouped[[
            f"{level}_id",
            f"{level}_name",
            "cluster",
            "results",
            "cpl",
            "p75_rate_pct",
        ]].replace({np.nan: None}).to_dict(orient="records")[:50]
    }
