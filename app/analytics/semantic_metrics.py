"""Semantic Meta Ads metric extraction.

This module is intentionally local/no external AI. It converts raw Meta Ads
arrays such as actions/action_values/cost_per_action_type into stable columns
that the diagnostics engine can reason over.
"""
from __future__ import annotations

from typing import Any, Iterable
import math
import pandas as pd
import numpy as np


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        if isinstance(value, float) and math.isnan(value):
            return default
        return float(value)
    except Exception:
        return default


def safe_div(numerator: Any, denominator: Any) -> float:
    den = safe_float(denominator)
    return safe_float(numerator) / den if den else 0.0


def _extract_from_action_list(actions: Any, action_types: Iterable[str]) -> float:
    if not isinstance(actions, list):
        return 0.0
    wanted = set(action_types)
    total = 0.0
    for item in actions:
        if not isinstance(item, dict):
            continue
        if item.get('action_type') in wanted:
            total += safe_float(item.get('value', 0))
    return total


ACTION_ALIASES = {
    'landing_page_views': [
        'landing_page_view',
        'omni_landing_page_view',
    ],
    'add_to_cart': [
        'add_to_cart',
        'omni_add_to_cart',
        'offsite_conversion.fb_pixel_add_to_cart',
        'onsite_conversion.add_to_cart',
    ],
    'initiate_checkout': [
        'initiate_checkout',
        'omni_initiated_checkout',
        'offsite_conversion.fb_pixel_initiate_checkout',
        'onsite_conversion.initiate_checkout',
    ],
    'purchases': [
        'purchase',
        'omni_purchase',
        'offsite_conversion.fb_pixel_purchase',
        'onsite_conversion.purchase',
    ],
    'leads': [
        'lead',
        'onsite_conversion.lead_grouped',
        'offsite_complete_registration_add_meta_leads',
        'complete_registration',
    ],
    'messaging_conversations': [
        'messaging_conversation_started_7d',
        'onsite_conversion.messaging_conversation_started_7d',
        'onsite_conversion.messaging_first_reply',
    ],
    'app_installs': [
        'mobile_app_install',
        'app_install',
    ],
}

VALUE_ALIASES = {
    'purchase_value': [
        'purchase',
        'omni_purchase',
        'offsite_conversion.fb_pixel_purchase',
        'onsite_conversion.purchase',
    ],
}

COST_ALIASES = {
    'cost_per_purchase': ACTION_ALIASES['purchases'],
    'cost_per_lead': ACTION_ALIASES['leads'],
    'cost_per_messaging_conversation': ACTION_ALIASES['messaging_conversations'],
    'cost_per_add_to_cart': ACTION_ALIASES['add_to_cart'],
}


def expand_semantic_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with semantic action/value/rate columns.

    The function is defensive: if Meta did not return a field, it uses zero and
    keeps analysis running while exposing missingness later in diagnostics.
    """
    if df is None or df.empty:
        return df.copy() if df is not None else pd.DataFrame()

    out = df.copy()
    for col in [
        'spend', 'impressions', 'reach', 'frequency', 'ctr', 'cpc', 'cpm',
        'inline_link_clicks', 'clicks', 'results', 'video_p25', 'video_p50',
        'video_p75', 'video_p95', 'video_p100'
    ]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors='coerce').fillna(0.0)
        else:
            out[col] = 0.0

    actions = out['actions'] if 'actions' in out.columns else pd.Series([None] * len(out), index=out.index)
    action_values = out['action_values'] if 'action_values' in out.columns else pd.Series([None] * len(out), index=out.index)
    cost_actions = out['cost_per_action_type'] if 'cost_per_action_type' in out.columns else pd.Series([None] * len(out), index=out.index)

    for metric, aliases in ACTION_ALIASES.items():
        extracted = actions.apply(lambda x, aliases=aliases: _extract_from_action_list(x, aliases))
        out[metric] = extracted if metric not in out.columns else np.where(extracted > 0, extracted, pd.to_numeric(out[metric], errors='coerce').fillna(0.0))

    for metric, aliases in VALUE_ALIASES.items():
        extracted = action_values.apply(lambda x, aliases=aliases: _extract_from_action_list(x, aliases))
        out[metric] = extracted if metric not in out.columns else np.where(extracted > 0, extracted, pd.to_numeric(out[metric], errors='coerce').fillna(0.0))

    for metric, aliases in COST_ALIASES.items():
        extracted = cost_actions.apply(lambda x, aliases=aliases: _extract_from_action_list(x, aliases))
        out[metric] = extracted if metric not in out.columns else np.where(extracted > 0, extracted, pd.to_numeric(out[metric], errors='coerce').fillna(0.0))

    # Meta sometimes returns outbound_clicks/outbound_clicks_ctr as list actions.
    if 'outbound_clicks' in out.columns:
        out['outbound_clicks_value'] = out['outbound_clicks'].apply(
            lambda x: _extract_from_action_list(x, ['outbound_click']) if isinstance(x, list) else safe_float(x)
        )
    else:
        existing_outbound = out.get('outbound_clicks_value', out.get('outbound_clicks_count', 0.0))
        out['outbound_clicks_value'] = pd.to_numeric(existing_outbound, errors='coerce').fillna(0.0) if isinstance(existing_outbound, pd.Series) else 0.0

    out['link_clicks'] = out['inline_link_clicks']
    out['outbound_clicks_count'] = out['outbound_clicks_value']

    out['outbound_ctr_calc'] = np.where(out['impressions'] > 0, out['outbound_clicks_count'] / out['impressions'], 0.0)
    out['link_ctr_calc'] = np.where(out['impressions'] > 0, out['link_clicks'] / out['impressions'], 0.0)
    out['lpv_rate'] = np.where(out['outbound_clicks_count'] > 0, out['landing_page_views'] / out['outbound_clicks_count'], 0.0)
    out['atc_rate'] = np.where(out['landing_page_views'] > 0, out['add_to_cart'] / out['landing_page_views'], 0.0)
    out['checkout_rate'] = np.where(out['add_to_cart'] > 0, out['initiate_checkout'] / out['add_to_cart'], 0.0)
    out['purchase_rate'] = np.where(out['landing_page_views'] > 0, out['purchases'] / out['landing_page_views'], 0.0)
    out['checkout_to_purchase_rate'] = np.where(out['initiate_checkout'] > 0, out['purchases'] / out['initiate_checkout'], 0.0)
    out['cpa_purchase'] = np.where(out['purchases'] > 0, out['spend'] / out['purchases'], 0.0)
    out['roas_calc'] = np.where(out['spend'] > 0, out['purchase_value'] / out['spend'], 0.0)
    out['signal_quality'] = np.where(out['outbound_clicks_count'] > 0, out['purchases'] / out['outbound_clicks_count'], 0.0)
    out['thumbstop_rate'] = np.where(out['impressions'] > 0, out['video_p25'] / out['impressions'], 0.0)
    out['hold_rate_50'] = np.where(out['video_p25'] > 0, out['video_p50'] / out['video_p25'], 0.0)
    out['hold_rate_75'] = np.where(out['video_p25'] > 0, out['video_p75'] / out['video_p25'], 0.0)

    return out


def aggregate_metrics(df: pd.DataFrame, level: str) -> pd.DataFrame:
    """Aggregate semantic metrics at requested entity level."""
    if df is None or df.empty:
        return pd.DataFrame()
    df = expand_semantic_metrics(df)
    id_col = f'{level}_id'
    name_col = f'{level}_name'
    if id_col not in df.columns:
        df[id_col] = 'ALL'
    if name_col not in df.columns:
        df[name_col] = df[id_col]

    sum_cols = [
        'spend', 'impressions', 'reach', 'inline_link_clicks', 'link_clicks',
        'outbound_clicks_count', 'landing_page_views', 'add_to_cart',
        'initiate_checkout', 'purchases', 'purchase_value', 'leads',
        'messaging_conversations', 'app_installs', 'video_p25', 'video_p50',
        'video_p75', 'video_p95', 'video_p100', 'results'
    ]
    agg_map = {c: 'sum' for c in sum_cols if c in df.columns}
    if 'frequency' in df.columns:
        agg_map['frequency'] = 'mean'
    if 'ctr' in df.columns:
        agg_map['ctr'] = 'mean'
    if 'cpm' in df.columns:
        agg_map['cpm'] = 'mean'
    if 'cpc' in df.columns:
        agg_map['cpc'] = 'mean'
    for context_col in ['objective', 'optimization_goal', 'billing_event', 'destination_type']:
        if context_col in df.columns:
            agg_map[context_col] = 'first'

    grouped = df.groupby([id_col, name_col], dropna=False).agg(agg_map).reset_index()
    grouped = expand_semantic_metrics(grouped)
    return grouped
