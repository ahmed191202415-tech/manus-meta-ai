"""SQLite storage for accumulated Meta Ads intelligence runs."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import pandas as pd

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS raw_insights_daily (
  date TEXT,
  account_id TEXT,
  campaign_id TEXT,
  adset_id TEXT,
  ad_id TEXT,
  level TEXT,
  objective TEXT,
  optimization_goal TEXT,
  billing_event TEXT,
  breakdown_signature TEXT DEFAULT '',
  spend REAL,
  impressions REAL,
  reach REAL,
  frequency REAL,
  clicks REAL,
  inline_link_clicks REAL,
  outbound_clicks REAL,
  actions TEXT,
  action_values TEXT,
  cost_per_action_type TEXT,
  raw_json TEXT,
  UNIQUE(date, account_id, campaign_id, adset_id, ad_id, level, breakdown_signature)
);
CREATE TABLE IF NOT EXISTS derived_metrics_daily (
  date TEXT,
  account_id TEXT,
  campaign_id TEXT,
  adset_id TEXT,
  ad_id TEXT,
  level TEXT,
  breakdown_signature TEXT DEFAULT '',
  spend REAL,
  impressions REAL,
  reach REAL,
  frequency REAL,
  link_clicks REAL,
  outbound_clicks REAL,
  landing_page_views REAL,
  add_to_cart REAL,
  initiate_checkout REAL,
  purchases REAL,
  leads REAL,
  messaging_conversations REAL,
  purchase_value REAL,
  ctr_link REAL,
  outbound_ctr REAL,
  lpv_rate REAL,
  atc_rate REAL,
  checkout_rate REAL,
  purchase_rate REAL,
  cpa REAL,
  cost_per_purchase REAL,
  roas REAL,
  signal_quality REAL,
  UNIQUE(date, account_id, campaign_id, adset_id, ad_id, level, breakdown_signature)
);
CREATE TABLE IF NOT EXISTS baselines (
  metric TEXT,
  entity_level TEXT,
  entity_id TEXT,
  baseline_7d REAL,
  baseline_14d REAL,
  baseline_30d REAL,
  mean REAL,
  median REAL,
  std REAL,
  p10 REAL,
  p90 REAL,
  samples INTEGER,
  UNIQUE(metric, entity_level, entity_id)
);
CREATE TABLE IF NOT EXISTS diagnostics_daily (
  run_id TEXT,
  date TEXT,
  entity_level TEXT,
  entity_id TEXT,
  scenario TEXT,
  severity TEXT,
  confidence TEXT,
  evidence_json TEXT,
  diagnosis_ar TEXT,
  recommended_action TEXT,
  next_metric TEXT
);
CREATE TABLE IF NOT EXISTS relationship_edges (
  run_id TEXT,
  source_metric TEXT,
  target_metric TEXT,
  relation_type TEXT,
  weight REAL,
  confidence TEXT,
  explanation_ar TEXT,
  evidence_json TEXT
);
CREATE TABLE IF NOT EXISTS analysis_runs (
  run_id TEXT PRIMARY KEY,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  scope TEXT,
  level TEXT,
  period TEXT,
  phase TEXT,
  completed_modules TEXT,
  skipped_modules TEXT,
  errors TEXT
);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA_SQL)
    con.commit()
    return con


def _json_safe(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


def prepare_raw_for_storage(df: pd.DataFrame, level: str = "campaign", breakdown_signature: str = "") -> pd.DataFrame:
    out = df.copy() if df is not None else pd.DataFrame()
    for col in ["date", "account_id", "campaign_id", "adset_id", "ad_id", "objective", "optimization_goal", "billing_event"]:
        if col not in out.columns:
            out[col] = ""
    for col in ["spend", "impressions", "reach", "frequency", "clicks", "inline_link_clicks", "outbound_clicks"]:
        if col not in out.columns:
            out[col] = 0
    for col in ["actions", "action_values", "cost_per_action_type"]:
        if col not in out.columns:
            out[col] = "[]"
        out[col] = out[col].apply(_json_safe)
    out["level"] = level
    out["breakdown_signature"] = breakdown_signature
    out["raw_json"] = df.apply(lambda r: json.dumps(r.to_dict(), ensure_ascii=False, default=str), axis=1) if len(out) else ""
    cols = [
        "date", "account_id", "campaign_id", "adset_id", "ad_id", "level", "objective", "optimization_goal", "billing_event",
        "breakdown_signature", "spend", "impressions", "reach", "frequency", "clicks", "inline_link_clicks", "outbound_clicks",
        "actions", "action_values", "cost_per_action_type", "raw_json"
    ]
    return out[cols]


def upsert_df(con: sqlite3.Connection, table: str, df: pd.DataFrame) -> None:
    if df is None or df.empty:
        return
    placeholders = ",".join(["?"] * len(df.columns))
    cols = ",".join(df.columns)
    sql = f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({placeholders})"
    con.executemany(sql, df.where(pd.notnull(df), None).itertuples(index=False, name=None))
    con.commit()


def save_run(con: sqlite3.Connection, run_id: str, **kwargs: Any) -> None:
    row = {"run_id": run_id, **kwargs}
    for key in ["completed_modules", "skipped_modules", "errors"]:
        if key in row and not isinstance(row[key], str):
            row[key] = json.dumps(row[key], ensure_ascii=False, default=str)
    cols = list(row.keys())
    sql = f"INSERT OR REPLACE INTO analysis_runs ({','.join(cols)}) VALUES ({','.join(['?']*len(cols))})"
    con.execute(sql, [row[c] for c in cols])
    con.commit()
