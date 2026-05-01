"""Internal baselines for Meta Ads metrics.

Baselines are account/campaign/adset/ad internal references. They are preferred
over generic market benchmarks for judgment labels such as high/low.
"""
from __future__ import annotations

from typing import Iterable, List
import pandas as pd

DEFAULT_BASELINE_METRICS = [
    'spend', 'impressions', 'reach', 'frequency', 'ctr_link', 'outbound_ctr',
    'lpv_rate', 'atc_rate', 'checkout_rate', 'purchase_rate', 'cpa',
    'cost_per_purchase', 'roas', 'signal_quality', 'cpm'
]


def _window_stat(group: pd.DataFrame, metric: str, days: int) -> float:
    if 'date' in group.columns:
        g = group.sort_values('date').tail(days)
    else:
        g = group.tail(days)
    s = pd.to_numeric(g.get(metric), errors='coerce').dropna()
    return float(s.mean()) if len(s) else 0.0


def compute_internal_baselines(
    df: pd.DataFrame,
    entity_col: str = 'campaign_id',
    entity_level: str = 'campaign',
    metrics: Iterable[str] | None = None,
) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=['metric', 'entity_level', 'entity_id', 'baseline_7d', 'baseline_14d', 'baseline_30d', 'mean', 'median', 'std', 'p10', 'p90', 'samples'])
    metrics = list(metrics or DEFAULT_BASELINE_METRICS)
    if entity_col not in df.columns:
        df = df.copy()
        df[entity_col] = 'all'
    rows: List[dict] = []
    for entity_id, group in df.groupby(entity_col, dropna=False):
        for metric in metrics:
            if metric not in group.columns:
                continue
            s = pd.to_numeric(group[metric], errors='coerce').dropna()
            if len(s) == 0:
                continue
            rows.append({
                'metric': metric,
                'entity_level': entity_level,
                'entity_id': str(entity_id or 'unknown'),
                'baseline_7d': _window_stat(group, metric, 7),
                'baseline_14d': _window_stat(group, metric, 14),
                'baseline_30d': _window_stat(group, metric, 30),
                'mean': float(s.mean()),
                'median': float(s.median()),
                'std': float(s.std(ddof=0)) if len(s) > 1 else 0.0,
                'p10': float(s.quantile(0.10)),
                'p90': float(s.quantile(0.90)),
                'samples': int(len(s)),
            })
    return pd.DataFrame(rows)
