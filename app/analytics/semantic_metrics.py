"""Semantic Meta Ads metric extraction.

This module is intentionally local/no external AI. It converts raw Meta Ads
arrays such as actions/action_values/cost_per_action_type into stable columns
that the diagnostics engine can reason over.
"""
from __future__ import annotations

from typing import Any, Iterable
import json
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


def _coerce_action_list(actions: Any) -> list:
    if actions is None:
        return []
    if isinstance(actions, list):
        return actions
    if isinstance(actions, dict):
        return [actions]
    if isinstance(actions, str):
        value = actions.strip()
        if not value:
            return []
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict):
                return [parsed]
        except Exception:
            return []
    return []


def _extract_from_action_list(actions: Any, action_types: Iterable[str]) -> float:
    action_list = _coerce_action_list(actions)
    wanted = set(action_types)
    total = 0.0
    for item in action_list:
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
        'onsite_conversion.total_messaging_connection',
        'onsite_conversion.messaging_conversation_replied_7d',
        'onsite_conversion.messaging_welcome_message_view',
    ],
    'page_engagement': [
        'page_engagement', 'post_engagement', 'post_reaction', 'like', 'comment', 'post', 'post_save', 'post_share',
    ],
    'content_interactions': [
        'post_engagement', 'post_reaction', 'post_interaction', 'post_interaction_gross', 'post_interaction_net', 'comment', 'like', 'post_save', 'post_share',
    ],
    'video_views': [
        'video_view', 'thruplay', 'video_p25_watched_actions', 'video_p50_watched_actions', 'video_p75_watched_actions', 'video_p95_watched_actions', 'video_p100_watched_actions',
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
        'video_p75', 'video_p95', 'video_p100', 'unique_clicks', 'unique_inline_link_clicks'
    ]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors='coerce').fillna(0.0)
        else:
            out[col] = 0.0

    actions = out['actions'] if 'actions' in out.columns else pd.Series([None] * len(out), index=out.index)
    action_values = out['action_values'] if 'action_values' in out.columns else pd.Series([None] * len(out), index=out.index)
    cost_actions = out['cost_per_action_type'] if 'cost_per_action_type' in out.columns else pd.Series([None] * len(out), index=out.index)

    for metric, aliases in ACTION_ALIASES.items():
        out[metric] = actions.apply(lambda x, aliases=aliases: _extract_from_action_list(x, aliases))

    for metric, aliases in VALUE_ALIASES.items():
        out[metric] = action_values.apply(lambda x, aliases=aliases: _extract_from_action_list(x, aliases))

    for metric, aliases in COST_ALIASES.items():
        out[metric] = cost_actions.apply(lambda x, aliases=aliases: _extract_from_action_list(x, aliases))

    # Meta sometimes returns outbound_clicks/outbound_clicks_ctr as list actions.
    if 'outbound_clicks' in out.columns:
        out['outbound_clicks_value'] = out['outbound_clicks'].apply(
            lambda x: _extract_from_action_list(x, ['outbound_click']) if isinstance(x, list) else safe_float(x)
        )
    else:
        out['outbound_clicks_value'] = 0.0

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

    # Cross-campaign semantic rates used by relationship and synthesis layers.
    out['ctr_link'] = out['link_ctr_calc']
    out['outbound_ctr'] = out['outbound_ctr_calc']
    out['cpm_calc'] = np.where(out['impressions'] > 0, out['spend'] / out['impressions'] * 1000, out['cpm'])
    out['cpc_link'] = np.where(out['link_clicks'] > 0, out['spend'] / out['link_clicks'], out['cpc'])
    out['cost_per_result'] = np.where(out['results'] > 0, out['spend'] / out['results'], 0.0)
    out['cost_per_message'] = np.where(out['messaging_conversations'] > 0, out['spend'] / out['messaging_conversations'], 0.0)
    out['message_start_rate'] = np.where(out['impressions'] > 0, out['messaging_conversations'] / out['impressions'], 0.0)
    out['click_to_message_rate'] = np.where(out['link_clicks'] > 0, out['messaging_conversations'] / out['link_clicks'], 0.0)
    out['result_rate_per_1000_reach'] = np.where(out['reach'] > 0, out['results'] / out['reach'] * 1000, 0.0)
    out['engagement_rate_calc'] = np.where(out['impressions'] > 0, out.get('content_interactions', 0) / out['impressions'], 0.0)
    out['budget_signal_score'] = np.where(out['spend'] > 0, out['results'] / out['spend'], 0.0)

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
        'messaging_conversations', 'app_installs', 'page_engagement', 'content_interactions', 'video_views',
        'video_p25', 'video_p50', 'video_p75', 'video_p95', 'video_p100', 'results'
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
    for col in ['ctr_link','outbound_ctr','cpm_calc','cpc_link','cost_per_result','cost_per_message','message_start_rate','click_to_message_rate','result_rate_per_1000_reach','engagement_rate_calc','budget_signal_score','thumbstop_rate','hold_rate_50','hold_rate_75']:
        if col in df.columns:
            agg_map[col] = 'mean'

    grouped = df.groupby([id_col, name_col], dropna=False).agg(agg_map).reset_index()
    grouped = expand_semantic_metrics(grouped)
    return grouped
