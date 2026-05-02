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


def _date_range_from_preset(date_preset: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    from datetime import date, timedelta
    if not date_preset:
        return None, None
    today = date.today()
    preset = str(date_preset)
    if preset == 'yesterday':
        d = today - timedelta(days=1)
        return d.isoformat(), d.isoformat()
    if preset == 'today':
        return today.isoformat(), today.isoformat()
    if preset.startswith('last_') and preset.endswith('d'):
        try:
            n = int(preset.replace('last_', '').replace('d', ''))
            return (today - timedelta(days=n)).isoformat(), today.isoformat()
        except Exception:
            return None, None
    return None, None


def cached_raw_insights(account_id: str, level: str, since: Optional[str], until: Optional[str], campaign_id: Optional[str] = None, max_rows: int = 5000, date_preset: Optional[str] = None) -> pd.DataFrame:
    if not enabled():
        return pd.DataFrame()
    if not since and not until and date_preset:
        since, until = _date_range_from_preset(date_preset)
    params={'select':'*','account_id':f'eq.{account_id}','level':f'eq.{level}','order':'date.asc'}
    if since and until:
        params['and']=f'(date.gte.{since},date.lte.{until})'
    elif since:
        params['date']=f'gte.{since}'
    elif until:
        params['date']=f'lte.{until}'
    if campaign_id:
        params['campaign_id']=f'eq.{campaign_id}'
    rows=_get('raw_insights_daily', params, max_rows)
    if not rows:
        return pd.DataFrame()
    df=pd.DataFrame(rows)
    # Strict guard: never return rows outside requested campaign.
    if campaign_id and 'campaign_id' in df.columns:
        df = df[df['campaign_id'].astype(str) == str(campaign_id)]
    if df.empty:
        return pd.DataFrame()
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
