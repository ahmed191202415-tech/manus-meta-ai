"""Supabase-backed cache reads and scheduled sync helpers."""
from __future__ import annotations
from typing import Any, Dict, List, Optional
import os, json
import requests
import pandas as pd

from app.analytics import supabase_storage


def _base_key():
    base=(os.getenv('INTELLIGENCE_SUPABASE_URL') or os.getenv('SUPABASE_URL') or '').rstrip('/')
    key=os.getenv('INTELLIGENCE_SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_SERVICE_ROLE_KEY') or ''
    return base, key


def enabled() -> bool:
    base,key=_base_key()
    return bool(base and key)


def _headers(key: str) -> Dict[str, str]:
    return {'apikey':key,'Authorization':f'Bearer {key}','Accept':'application/json','Content-Type':'application/json'}


def _get(table: str, params: Dict[str, Any], limit: int = 5000) -> List[Dict[str, Any]]:
    base,key=_base_key()
    if not base or not key:
        return []
    params={**params,'limit':str(limit)}
    r=requests.get(f'{base}/rest/v1/{table}', headers=_headers(key), params=params, timeout=90)
    if r.status_code >= 300:
        return []
    return r.json() if r.text else []


def cached_raw_insights(account_id: str, level: str, since: Optional[str], until: Optional[str], campaign_id: Optional[str] = None, max_rows: int = 5000) -> pd.DataFrame:
    if not enabled():
        return pd.DataFrame()
    params={'select':'*','account_id':f'eq.{account_id}','level':f'eq.{level}','order':'date.asc'}
    if since: params['date']=f'gte.{since}'
    if until: params['date']=f'lte.{until}' if 'date' not in params else params['date']
    # PostgREST cannot use two date keys in dict; use and= for range when both exist.
    if since and until:
        params.pop('date', None)
        params['and']=f'(date.gte.{since},date.lte.{until})'
    if campaign_id:
        params['campaign_id']=f'eq.{campaign_id}'
    rows=_get('raw_insights_daily', params, max_rows)
    if not rows:
        return pd.DataFrame()
    df=pd.DataFrame(rows)
    for col in ['actions','action_values','cost_per_action_type']:
        if col in df.columns:
            def parse(v):
                if isinstance(v,(list,dict)): return v
                try: return json.loads(v) if v else []
                except Exception: return []
            df[col]=df[col].apply(parse)
    if 'date' in df.columns and 'date_start' not in df.columns:
        df['date_start']=df['date']
    return df


def cache_coverage(df: pd.DataFrame, min_rows: int = 3) -> Dict[str, Any]:
    if df is None or df.empty:
        return {'hit':False,'rows':0,'days':0,'reason':'empty'}
    days=int(df.get('date', df.get('date_start', pd.Series(dtype=object))).nunique()) if len(df) else 0
    return {'hit': len(df) >= min_rows, 'rows': int(len(df)), 'days': days, 'reason':'ok' if len(df)>=min_rows else 'too_few_rows'}


def save_sync_status(payload: Dict[str, Any]) -> None:
    # Reuse analysis_runs for sync audit so no extra SQL migration is required.
    try:
        from app.analytics.supabase_storage import _post
        _post('analysis_runs', [payload], on_conflict='run_id')
    except Exception:
        pass
