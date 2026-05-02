"""Statistical skills layer for Meta Ads raw/enriched data.

This layer runs locally after Meta data is fetched or loaded from storage.
It does not call Meta, so it does not affect Meta API limits.
"""
from __future__ import annotations

from typing import Any, Dict, List
import math
import numpy as np
import pandas as pd
from scipy import stats
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score


def _num(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series([0.0] * len(df), index=df.index, dtype="float64")
    return pd.to_numeric(df[col], errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(0.0)


def _safe_div(a: Any, b: Any) -> float:
    try:
        a = float(a or 0)
        b = float(b or 0)
        if b == 0 or math.isnan(b):
            return 0.0
        return a / b
    except Exception:
        return 0.0


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v or 0)
        if math.isnan(x) or math.isinf(x):
            return default
        return x
    except Exception:
        return default


def add_statistical_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add ratios and safety-normalized features used by all later layers."""
    out = df.copy() if df is not None else pd.DataFrame()
    if out.empty:
        return out
    for col in ["spend","impressions","reach","frequency","inline_link_clicks","link_clicks","outbound_clicks_count","results","landing_page_views","add_to_cart","initiate_checkout","purchases","purchase_value","messaging_conversations","leads","video_p25","video_p50","video_p75","video_p95","video_p100","cpm","cpc","ctr"]:
        if col not in out.columns:
            out[col] = 0.0
        out[col] = _num(out, col)
    out["stat_ctr"] = np.where(out["impressions"] > 0, (out["inline_link_clicks"] + out["link_clicks"]) / out["impressions"], 0.0)
    out["stat_result_rate"] = np.where(out["impressions"] > 0, out["results"] / out["impressions"], 0.0)
    out["stat_cpa"] = np.where(out["results"] > 0, out["spend"] / out["results"], np.nan)
    out["stat_outbound_ctr"] = np.where(out["impressions"] > 0, out["outbound_clicks_count"] / out["impressions"], 0.0)
    out["stat_lpv_rate"] = np.where(out["outbound_clicks_count"] > 0, out["landing_page_views"] / out["outbound_clicks_count"], 0.0)
    out["stat_atc_rate"] = np.where(out["landing_page_views"] > 0, out["add_to_cart"] / out["landing_page_views"], 0.0)
    out["stat_checkout_rate"] = np.where(out["add_to_cart"] > 0, out["initiate_checkout"] / out["add_to_cart"], 0.0)
    out["stat_purchase_rate"] = np.where(out["initiate_checkout"] > 0, out["purchases"] / out["initiate_checkout"], 0.0)
    out["stat_roas"] = np.where(out["spend"] > 0, out["purchase_value"] / out["spend"], 0.0)
    out["stat_signal_quality"] = np.where(out["outbound_clicks_count"] > 0, out["purchases"] / out["outbound_clicks_count"], 0.0)
    out["stat_cost_per_message"] = np.where(out["messaging_conversations"] > 0, out["spend"] / out["messaging_conversations"], np.nan)
    out["stat_cost_per_lead"] = np.where(out["leads"] > 0, out["spend"] / out["leads"], np.nan)
    for p in [25,50,75,95,100]:
        out[f"stat_video_p{p}_rate"] = np.where(out["impressions"] > 0, out.get(f"video_p{p}", 0) / out["impressions"], 0.0)
    return out.replace([np.inf, -np.inf], np.nan)


def _metric_baseline(series: pd.Series) -> Dict[str, Any]:
    x = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if x.empty:
        return {"mean":0.0,"median":0.0,"std":0.0,"p10":0.0,"p90":0.0,"samples":0}
    return {"mean":float(x.mean()),"median":float(x.median()),"std":float(x.std(ddof=0) or 0.0),"p10":float(x.quantile(0.10)),"p90":float(x.quantile(0.90)),"samples":int(len(x))}


def _trend_slope(series: pd.Series) -> float:
    x = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if len(x) < 2:
        return 0.0
    try:
        return float(np.polyfit(np.arange(len(x), dtype=float), x.to_numpy(dtype=float), 1)[0])
    except Exception:
        return 0.0


def _z_anomalies(df: pd.DataFrame, metric: str, entity_cols: List[str]) -> List[Dict[str, Any]]:
    if metric not in df.columns or len(df) < 4:
        return []
    vals = _num(df, metric)
    if vals.nunique(dropna=True) < 2:
        return []
    z = np.abs(stats.zscore(vals, nan_policy="omit"))
    z = np.nan_to_num(z)
    out = df.copy()
    out["_z"] = z
    an = out[out["_z"] >= 2.0].sort_values("_z", ascending=False).head(20)
    rows=[]
    for _, r in an.iterrows():
        rows.append({
            "metric": metric,
            "z_score": round(float(r.get("_z",0)),4),
            "value": _safe_float(r.get(metric)),
            "date": str(r.get("date_start") or r.get("date") or ""),
            "entity": {c: str(r.get(c,"")) for c in entity_cols if c in r.index},
        })
    return rows


def _rank_entities(df: pd.DataFrame, level: str, top_n: int = 10) -> Dict[str, Any]:
    id_col=f"{level}_id"; name_col=f"{level}_name"
    if id_col not in df.columns:
        return {}
    work=df.copy()
    work["_clicks"]=_num(work,"inline_link_clicks")+_num(work,"link_clicks")
    grouped=work.groupby([id_col, name_col] if name_col in work.columns else [id_col], dropna=False).agg(
        spend=("spend","sum"), impressions=("impressions","sum"), reach=("reach","sum"), clicks=("_clicks","sum"), results=("results","sum"), frequency=("frequency","mean"), cpm=("cpm","mean")
    ).reset_index()
    grouped["ctr"] = grouped.apply(lambda r: _safe_div(r["clicks"], r["impressions"]), axis=1)
    grouped["cpa"] = grouped.apply(lambda r: _safe_div(r["spend"], r["results"]), axis=1)
    grouped["result_rate"] = grouped.apply(lambda r: _safe_div(r["results"], r["impressions"]), axis=1)
    def recs(g): return g.replace([np.inf,-np.inf],np.nan).fillna(0).to_dict(orient="records")
    return {
        "top_by_results": recs(grouped.sort_values("results", ascending=False).head(top_n)),
        "top_by_efficiency": recs(grouped[grouped["results"]>0].sort_values("cpa", ascending=True).head(top_n)),
        "bottom_by_spend_no_result": recs(grouped.sort_values(["results","spend"], ascending=[True,False]).head(top_n)),
    }


def _decision_scores(df: pd.DataFrame, level: str, top_n: int = 50) -> List[Dict[str, Any]]:
    ranks=_rank_entities(df, level, top_n=100)
    rows=ranks.get("top_by_results") or []
    if not rows:
        return []
    g=pd.DataFrame(rows)
    if g.empty:
        return []
    spend_max=max(float(g["spend"].max() or 0),1)
    result_rate_max=max(float(g["result_rate"].max() or 0),1e-9)
    cpa_series=pd.to_numeric(g["cpa"], errors="coerce").replace([np.inf,-np.inf], np.nan).fillna(0)
    cpa_max=max(float(cpa_series.max() or 0),1)
    ctr_max=max(float(pd.to_numeric(g["ctr"], errors="coerce").max() or 0),1e-9)
    g["decision_score"]=(g["spend"]/spend_max*10)+(g["result_rate"]/result_rate_max*35)+(g["ctr"]/ctr_max*25)+((1-(cpa_series/cpa_max))*30)
    def decide(r):
        if r["decision_score"] >= 70 and r["results"] >= 3: return "SCALE"
        if r["decision_score"] >= 45: return "HOLD"
        return "KILL"
    g["decision"] = g.apply(decide, axis=1)
    return g.sort_values("decision_score", ascending=False).head(top_n).replace([np.inf,-np.inf],np.nan).fillna(0).to_dict(orient="records")


def _clusters(df: pd.DataFrame, level: str) -> Dict[str, Any]:
    ranks=_rank_entities(df, level, top_n=500)
    rows=ranks.get("top_by_results") or []
    g=pd.DataFrame(rows)
    if len(g) < 3:
        return {"message":"Not enough entities for clustering"}
    features=g[["ctr","result_rate","cpa","frequency"]].replace([np.inf,-np.inf],np.nan).fillna(0)
    k=min(3,len(g))
    try:
        scaled=StandardScaler().fit_transform(features)
        model=KMeans(n_clusters=k, n_init=10, random_state=42)
        g["cluster"]=model.fit_predict(scaled)
        summary=g.groupby("cluster").agg({"ctr":"mean","result_rate":"mean","cpa":"mean","frequency":"mean","results":"sum","spend":"sum"}).reset_index()
        return {"clusters":summary.replace([np.inf,-np.inf],np.nan).fillna(0).to_dict(orient="records"),"entities":g.head(100).replace([np.inf,-np.inf],np.nan).fillna(0).to_dict(orient="records")}
    except Exception as exc:
        return {"message":str(exc)}


def _forecast(df: pd.DataFrame) -> Dict[str, Any]:
    if "date_start" not in df.columns and "date" not in df.columns:
        return {"message":"No daily date column"}
    dcol="date_start" if "date_start" in df.columns else "date"
    work=df.copy()
    work[dcol]=pd.to_datetime(work[dcol], errors="coerce")
    daily=work.groupby(dcol, dropna=True).agg(spend=("spend","sum"), results=("results","sum"), impressions=("impressions","sum")).reset_index().sort_values(dcol)
    if len(daily) < 4:
        return {"message":"Not enough daily points"}
    X=np.arange(len(daily)).reshape(-1,1)
    out={}
    for metric in ["spend","results","impressions"]:
        y=pd.to_numeric(daily[metric], errors="coerce").fillna(0).to_numpy()
        try:
            model=LinearRegression().fit(X,y)
            pred=model.predict(np.arange(len(daily), len(daily)+7).reshape(-1,1))
            fit=model.predict(X)
            out[metric]={"next_7":[round(float(v),2) for v in pred],"r2":round(float(r2_score(y,fit)),4),"slope":round(float(model.coef_[0]),4)}
        except Exception:
            pass
    return out


def build_statistical_profile(df: pd.DataFrame, level: str = "ad") -> Dict[str, Any]:
    enriched=add_statistical_features(df)
    if enriched.empty:
        return {"rows":0,"metrics":{},"baselines":{},"anomalies":[],"trends":{},"rankings":{},"decision_scores":[],"clusters":{},"forecast":{}}
    metrics=["spend","impressions","reach","frequency","cpm","cpc","ctr","stat_ctr","results","stat_cpa","stat_result_rate","stat_lpv_rate","stat_roas","stat_signal_quality","messaging_conversations","leads","purchases"]
    baselines={m:_metric_baseline(enriched[m]) for m in metrics if m in enriched.columns}
    trends={m:_trend_slope(enriched.sort_values("date_start")[m] if "date_start" in enriched.columns and m in enriched.columns else enriched[m]) for m in metrics if m in enriched.columns}
    entity_cols=[c for c in [f"{level}_id",f"{level}_name","campaign_id","campaign_name","adset_id","adset_name","ad_id","ad_name"] if c in enriched.columns]
    anomalies=[]
    for m in ["stat_ctr","stat_cpa","cpm","frequency","results","spend","stat_lpv_rate","stat_signal_quality"]:
        anomalies.extend(_z_anomalies(enriched, m, entity_cols))
    return {
        "rows": int(len(enriched)),
        "features_added": [c for c in enriched.columns if c.startswith("stat_")],
        "baselines": baselines,
        "anomalies": anomalies[:50],
        "trends": trends,
        "rankings": _rank_entities(enriched, level),
        "decision_scores": _decision_scores(enriched, level),
        "clusters": _clusters(enriched, level),
        "forecast": _forecast(enriched),
        "sample_sufficiency": {"rows": int(len(enriched)), "days": int(enriched.get("date_start", pd.Series(dtype=object)).nunique()) if "date_start" in enriched.columns else 0, "level": level},
    }
