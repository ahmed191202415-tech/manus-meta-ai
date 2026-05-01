"""Unified local pipeline for Meta Ads intelligence.

Works with CSV/XLSX/JSON exports now, and can be fed by Meta API later.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Dict

import pandas as pd

from app.analytics.analysis_storage import connect, prepare_raw_for_storage, save_run, upsert_df, save_relationship_edges, save_diagnostics
from app.analytics.semantic_metrics import expand_semantic_metrics
from app.analytics.intelligent_diagnostics import build_intelligence_diagnostics
from app.analytics.relationship_engine import discover_relationship_edges
from app.analytics.report_builder import build_dynamic_report_ar, build_skipped_sections
from app.analytics.baseline_engine import compute_internal_baselines


def load_export(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == '.csv':
        return pd.read_csv(path)
    if suffix in {'.xlsx', '.xls'}:
        return pd.read_excel(path)
    if suffix == '.json':
        data = json.loads(path.read_text(encoding='utf-8'))
        if isinstance(data, dict) and 'data' in data:
            data = data['data']
        return pd.DataFrame(data)
    raise ValueError(f'Unsupported file type: {suffix}')


def _basic_metrics(df: pd.DataFrame) -> Dict[str, Any]:
    metrics: Dict[str, Any] = {'rows': int(len(df))}
    mean_cols = {'frequency', 'ctr_link', 'outbound_ctr', 'cpa', 'roas', 'signal_quality'}
    for col in ['spend', 'impressions', 'reach', 'frequency', 'ctr_link', 'outbound_ctr', 'cpa', 'roas', 'signal_quality']:
        if col in df.columns:
            series = pd.to_numeric(df[col], errors='coerce').fillna(0)
            metrics[col] = float(series.mean() if col in mean_cols else series.sum())
    return metrics


def _derived_for_storage(df: pd.DataFrame, level: str = 'campaign') -> pd.DataFrame:
    out = df.copy()
    for col in ['date', 'account_id', 'campaign_id', 'adset_id', 'ad_id']:
        if col not in out.columns:
            out[col] = ''
    out['level'] = level
    out['breakdown_signature'] = ''
    if 'link_clicks' not in out.columns:
        if 'inline_link_clicks' in out.columns:
            out['link_clicks'] = out['inline_link_clicks']
        else:
            out['link_clicks'] = 0
    keep = [
        'date', 'account_id', 'campaign_id', 'adset_id', 'ad_id', 'level', 'breakdown_signature',
        'spend', 'impressions', 'reach', 'frequency', 'link_clicks', 'outbound_clicks',
        'landing_page_views', 'add_to_cart', 'initiate_checkout', 'purchases', 'leads',
        'messaging_conversations', 'purchase_value', 'ctr_link', 'outbound_ctr', 'lpv_rate',
        'atc_rate', 'checkout_rate', 'purchase_rate', 'cpa', 'cost_per_purchase', 'roas', 'signal_quality'
    ]
    for col in keep:
        if col not in out.columns:
            out[col] = 0 if col not in {'date', 'account_id', 'campaign_id', 'adset_id', 'ad_id', 'level', 'breakdown_signature'} else ''
    return out[keep]


def analyze_dataframe(
    df: pd.DataFrame,
    compare_df: pd.DataFrame | None = None,
    campaign_type: str = 'unknown',
    question: str = '',
    level: str = 'campaign',
    db_path: str | Path | None = None,
) -> Dict[str, Any]:
    run_id = str(uuid.uuid4())
    current = expand_semantic_metrics(df)
    previous = expand_semantic_metrics(compare_df) if compare_df is not None else current.iloc[0:0].copy()

    diagnostics_bundle = build_intelligence_diagnostics(current, previous, level=level, top_n=10)
    relationships = discover_relationship_edges(current)
    skipped = build_skipped_sections(current, campaign_type)
    metrics = _basic_metrics(current)

    result: Dict[str, Any] = {
        'run_id': run_id,
        'phase': 'basic+semantic+relationships+diagnostics+report',
        'summary_ar': diagnostics_bundle.get('summary_ar') or 'تم تحليل البيانات عبر طبقات المقاييس والعلاقات والتشخيص.',
        'rows': int(len(current)),
        'metrics': metrics,
        'diagnostics': diagnostics_bundle.get('top_diagnostics', []),
        'human_insights': diagnostics_bundle.get('human_insights', []),
        'multivariate_synthesis': diagnostics_bundle.get('multivariate_synthesis', []),
        'relationships': relationships,
        'skipped_sections': skipped + diagnostics_bundle.get('missing_notes', []),
        'objective_notes': diagnostics_bundle.get('objective_notes', []),
    }
    result['report_markdown'] = build_dynamic_report_ar(result, campaign_type=campaign_type, question=question)

    if db_path:
        con = connect(db_path)
        upsert_df(con, 'raw_insights_daily', prepare_raw_for_storage(df, level=level))
        upsert_df(con, 'derived_metrics_daily', _derived_for_storage(current, level=level))
        entity_col = f'{level}_id' if f'{level}_id' in current.columns else 'campaign_id'
        baselines = compute_internal_baselines(current, entity_col=entity_col, entity_level=level)
        upsert_df(con, 'baselines', baselines)
        save_relationship_edges(con, run_id, relationships)
        save_diagnostics(con, run_id, result['diagnostics'], entity_level=level)
        save_run(
            con,
            run_id,
            scope='dataframe',
            level=level,
            period='',
            phase=result['phase'],
            completed_modules=['semantic_metrics', 'relationships', 'diagnostics', 'report'],
            skipped_modules=result['skipped_sections'],
            errors=[],
        )
        con.close()
    return result


def analyze_file(
    path: str | Path,
    compare_path: str | Path | None = None,
    campaign_type: str = 'unknown',
    question: str = '',
    level: str = 'campaign',
    db_path: str | Path | None = None,
) -> Dict[str, Any]:
    df = load_export(path)
    compare_df = load_export(compare_path) if compare_path else None
    return analyze_dataframe(df, compare_df=compare_df, campaign_type=campaign_type, question=question, level=level, db_path=db_path)
