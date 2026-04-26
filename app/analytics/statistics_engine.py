"""Statistical operations for Meta Ads diagnostics."""
from __future__ import annotations
from typing import Any, Optional
import math
import numpy as np
import pandas as pd


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        if isinstance(value, float) and math.isnan(value):
            return default
        return float(value)
    except Exception:
        return default


def pct_change(current: Any, previous: Any) -> Optional[float]:
    cur = safe_float(current)
    prev = safe_float(previous)
    if prev == 0:
        return None
    return (cur - prev) / prev


def direction(value: Optional[float], dead_zone: float = 0.03) -> str:
    if value is None:
        return 'unknown'
    if value > dead_zone:
        return 'up'
    if value < -dead_zone:
        return 'down'
    return 'flat'


def severity_from_score(score: float) -> str:
    if score >= 80:
        return 'critical'
    if score >= 60:
        return 'high'
    if score >= 35:
        return 'medium'
    return 'low'


def z_score(value: Any, mean: Any, std: Any) -> Optional[float]:
    std_f = safe_float(std)
    if std_f == 0:
        return None
    return (safe_float(value) - safe_float(mean)) / std_f


def rolling_baseline(series: pd.Series, window: int = 7) -> dict:
    numeric = pd.to_numeric(series, errors='coerce').dropna()
    if numeric.empty:
        return {'mean': 0.0, 'median': 0.0, 'std': 0.0, 'p10': 0.0, 'p90': 0.0}
    tail = numeric.tail(window)
    return {
        'mean': float(tail.mean()),
        'median': float(tail.median()),
        'std': float(tail.std(ddof=0) or 0.0),
        'p10': float(tail.quantile(0.10)),
        'p90': float(tail.quantile(0.90)),
    }


def trend_slope(values: pd.Series) -> float:
    numeric = pd.to_numeric(values, errors='coerce').dropna()
    if len(numeric) < 2:
        return 0.0
    x = np.arange(len(numeric), dtype=float)
    y = numeric.to_numpy(dtype=float)
    try:
        return float(np.polyfit(x, y, 1)[0])
    except Exception:
        return 0.0
