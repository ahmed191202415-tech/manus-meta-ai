"""Unified data access layer for analysis.

Purpose:
- Storage first.
- Strict scope guard.
- Bounded Meta fetch only when cache is missing.
- Timing/audit metadata for speed and trust.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional
import time
import pandas as pd

from app.analytics.preprocessing import fetch_insights_df
from app.analytics.storage_cache import cached_raw_insights, cache_coverage


@dataclass
class DataAccessAudit:
    source: str
    cache_checked: bool
    cache_hit: bool
    rows: int
    meta_calls: int
    elapsed_ms: int
    account_id: str
    campaign_id: Optional[str]
    level: str
    date_preset: Optional[str]
    since: Optional[str]
    until: Optional[str]
    strict_scope_passed: bool
    coverage: Dict[str, Any]
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def strict_scope_df(df: pd.DataFrame, campaign_id: str | None) -> pd.DataFrame:
    if df is None or df.empty or not campaign_id:
        return df
    if "campaign_id" not in df.columns:
        return df
    return df[df["campaign_id"].astype(str) == str(campaign_id)].copy()


def is_scope_clean(df: pd.DataFrame, campaign_id: str | None) -> bool:
    if df is None or df.empty or not campaign_id:
        return True
    if "campaign_id" not in df.columns:
        return True
    return set(df["campaign_id"].astype(str).dropna().unique().tolist()).issubset({str(campaign_id)})


def get_analysis_dataset(
    *,
    account_id: str,
    token: str,
    level: str,
    fields: Optional[str],
    date_preset: Optional[str],
    since: Optional[str],
    until: Optional[str],
    filters: Optional[str],
    sort: Optional[str],
    campaign_id: Optional[str],
    prefer_cache: bool = True,
) -> tuple[pd.DataFrame, Dict[str, Any]]:
    started = time.perf_counter()
    meta_calls = 0
    coverage: Dict[str, Any] = {"hit": False, "rows": 0, "reason": "not_checked"}
    source = "meta_api"
    reason = "cache_disabled"
    df = pd.DataFrame()

    if prefer_cache:
        cache_df = cached_raw_insights(
            account_id,
            level,
            since,
            until,
            campaign_id=campaign_id,
            date_preset=date_preset,
        )
        cache_df = strict_scope_df(cache_df, campaign_id)
        coverage = cache_coverage(cache_df)
        if coverage.get("hit"):
            df = cache_df
            source = "supabase_cache"
            reason = "cache_hit"
        else:
            reason = f"cache_miss:{coverage.get('reason')}"

    if df.empty:
        meta_calls += 1
        # Bounded fetch. The fetcher itself applies safe defaults. We do not fetch_all here.
        df = fetch_insights_df(
            account_id,
            token,
            level,
            fields,
            date_preset,
            since,
            until,
            filters,
            sort,
        )
        df = strict_scope_df(df, campaign_id)
        source = "meta_api"

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    audit = DataAccessAudit(
        source=source,
        cache_checked=prefer_cache,
        cache_hit=source == "supabase_cache",
        rows=int(len(df)) if df is not None else 0,
        meta_calls=meta_calls,
        elapsed_ms=elapsed_ms,
        account_id=str(account_id or ""),
        campaign_id=str(campaign_id) if campaign_id else None,
        level=level,
        date_preset=date_preset,
        since=since,
        until=until,
        strict_scope_passed=is_scope_clean(df, campaign_id),
        coverage=coverage,
        reason=reason,
    ).to_dict()
    return df, audit
