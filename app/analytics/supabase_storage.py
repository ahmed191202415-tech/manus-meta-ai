"""Supabase/PostgREST storage backend for Meta Ads intelligence.

Uses INTELLIGENCE_SUPABASE_URL plus INTELLIGENCE_SUPABASE_SERVICE_ROLE_KEY, falling back to SUPABASE_SERVICE_ROLE_KEY only when INTELLIGENCE_SUPABASE_URL is explicitly set. Service role should only be kept
server-side, e.g. Railway variables.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Iterable, List

import pandas as pd
import requests


SUPABASE_TABLES = {
    'raw': 'raw_insights_daily',
    'derived': 'derived_metrics_daily',
    'baselines': 'baselines',
    'runs': 'analysis_runs',
    'diagnostics': 'diagnostics_daily',
    'relationships': 'relationship_edges',
}


def enabled() -> bool:
    return (os.getenv('INTELLIGENCE_STORAGE', '').lower() == 'supabase' and bool(os.getenv('INTELLIGENCE_SUPABASE_URL')) and bool(os.getenv('INTELLIGENCE_SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_SERVICE_ROLE_KEY')))


def _headers() -> Dict[str, str]:
    key = os.getenv('INTELLIGENCE_SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_SERVICE_ROLE_KEY', '')
    return {
        'apikey': key,
        'Authorization': f'Bearer {key}',
        'Content-Type': 'application/json',
        'Prefer': 'return=minimal,resolution=merge-duplicates',
    }


def _endpoint(table: str, on_conflict: str | None = None) -> str:
    base = os.getenv('INTELLIGENCE_SUPABASE_URL', '').rstrip('/')
    url = f'{base}/rest/v1/{table}'
    if on_conflict:
        url += f'?on_conflict={on_conflict}'
    return url


def _json_obj(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return json.loads(s)
        except Exception:
            return value
    return value


def _clean(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if hasattr(value, 'isoformat'):
        try:
            return value.isoformat()
        except Exception:
            pass
    return value


def _df_records(df: pd.DataFrame, json_cols: Iterable[str] = ()) -> List[Dict[str, Any]]:
    if df is None or df.empty:
        return []
    json_cols = set(json_cols)
    records = []
    for row in df.to_dict(orient='records'):
        item = {}
        for k, v in row.items():
            if k in json_cols:
                item[k] = _json_obj(v)
            else:
                item[k] = _clean(v)
        records.append(item)
    return records


def _post(table: str, rows: List[Dict[str, Any]], on_conflict: str | None = None) -> None:
    if not rows:
        return
    response = requests.post(_endpoint(table, on_conflict=on_conflict), headers=_headers(), data=json.dumps(rows, ensure_ascii=False, default=str), timeout=90)
    if response.status_code >= 400:
        raise RuntimeError(f'Supabase insert failed for {table}: {response.status_code} {response.text[:1000]}')


def save_dataframe_outputs(
    *,
    run_id: str,
    raw_df: pd.DataFrame,
    raw_storage_df: pd.DataFrame,
    derived_df: pd.DataFrame,
    baselines_df: pd.DataFrame,
    relationships: List[Dict[str, Any]],
    diagnostics: List[Dict[str, Any]],
    result: Dict[str, Any],
    account_id: str = '',
    campaign_id: str = '',
    tenant_id: str = '',
    level: str = 'campaign',
    question: str = '',
    campaign_type: str = 'unknown',
) -> None:
    if not enabled():
        return

    raw_records = _df_records(raw_storage_df, json_cols={'actions', 'action_values', 'cost_per_action_type', 'raw_json'})
    for r in raw_records:
        r.setdefault('tenant_id', tenant_id or None)
        if account_id and not r.get('account_id'):
            r['account_id'] = account_id
        if campaign_id and not r.get('campaign_id'):
            r['campaign_id'] = campaign_id
    _post(SUPABASE_TABLES['raw'], raw_records, on_conflict='date,account_id,campaign_id,adset_id,ad_id,level,breakdown_signature')

    derived_records = _df_records(derived_df)
    for r in derived_records:
        r.setdefault('tenant_id', tenant_id or None)
        if account_id and not r.get('account_id'):
            r['account_id'] = account_id
        if campaign_id and not r.get('campaign_id'):
            r['campaign_id'] = campaign_id
    _post(SUPABASE_TABLES['derived'], derived_records, on_conflict='date,account_id,campaign_id,adset_id,ad_id,level,breakdown_signature')

    baseline_records = _df_records(baselines_df)
    for r in baseline_records:
        r.setdefault('tenant_id', tenant_id or None)
        r.setdefault('account_id', account_id or None)
    _post(SUPABASE_TABLES['baselines'], baseline_records, on_conflict='account_id,metric,entity_level,entity_id')

    run_record = [{
        'run_id': run_id,
        'tenant_id': tenant_id or None,
        'account_id': account_id or None,
        'campaign_id': campaign_id or None,
        'level': level,
        'period': '',
        'phase': result.get('phase'),
        'question': question,
        'campaign_type': campaign_type,
        'completed_modules': ['semantic_metrics', 'baselines', 'relationships', 'diagnostics', 'report'],
        'skipped_modules': result.get('skipped_sections', []),
        'errors': [],
        'result_json': result,
        'report_markdown': result.get('report_markdown', ''),
    }]
    _post(SUPABASE_TABLES['runs'], run_record, on_conflict='run_id')

    edge_rows = []
    for e in relationships or []:
        edge_rows.append({
            'run_id': run_id,
            'tenant_id': tenant_id or None,
            'account_id': account_id or None,
            'campaign_id': campaign_id or None,
            'source_metric': e.get('source_metric'),
            'target_metric': e.get('target_metric'),
            'relation_type': e.get('relation_type'),
            'weight': e.get('weight'),
            'confidence': e.get('confidence'),
            'explanation_ar': e.get('explanation_ar'),
            'evidence_json': e.get('evidence', {}),
        })
    _post(SUPABASE_TABLES['relationships'], edge_rows)

    diag_rows = []
    for d in diagnostics or []:
        entity = d.get('entity') if isinstance(d.get('entity'), dict) else {}
        diag_rows.append({
            'run_id': run_id,
            'tenant_id': tenant_id or None,
            'account_id': account_id or None,
            'campaign_id': campaign_id or None,
            'date': d.get('date') or None,
            'entity_level': level,
            'entity_id': str(entity.get('id') or d.get('entity_id') or ''),
            'scenario': d.get('scenario') or d.get('code') or d.get('family'),
            'severity': d.get('severity'),
            'confidence': d.get('confidence'),
            'evidence_json': d.get('evidence', {}),
            'diagnosis_ar': d.get('diagnosis_ar') or d.get('message') or d.get('explanation'),
            'recommended_action': d.get('decision_ar') or d.get('recommended_action') or d.get('action'),
            'next_metric': d.get('next_metric'),
        })
    _post(SUPABASE_TABLES['diagnostics'], diag_rows)
