"""Optional local SQLite persistence for intelligence diagnostics."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parents[2] / "exports" / "meta_intelligence.sqlite"


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS intelligence_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        account_id TEXT,
        level TEXT,
        since TEXT,
        until TEXT,
        compare_since TEXT,
        compare_until TEXT,
        diagnostics_count INTEGER,
        payload_json TEXT
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS diagnostic_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER,
        scenario TEXT,
        severity TEXT,
        score REAL,
        entity_level TEXT,
        entity_id TEXT,
        entity_name TEXT,
        diagnosis_ar TEXT,
        evidence_json TEXT,
        recommended_action_ar TEXT
    )
    """)
    con.commit()
    con.close()


def save_intelligence_run(
    account_id: str,
    level: str,
    since: str | None,
    until: str | None,
    compare_since: str | None,
    compare_until: str | None,
    result: dict[str, Any],
) -> int:
    init_db()
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        """
        INSERT INTO intelligence_runs(
            created_at, account_id, level, since, until, compare_since,
            compare_until, diagnostics_count, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.utcnow().isoformat(timespec="seconds"),
            account_id,
            level,
            since,
            until,
            compare_since,
            compare_until,
            int(result.get("diagnostics_count", 0)),
            json.dumps(result, ensure_ascii=False, default=str),
        ),
    )
    run_id = int(cur.lastrowid)
    for hit in result.get("diagnostics", result.get("top_diagnostics", [])) or []:
        cur.execute(
            """
            INSERT INTO diagnostic_events(
                run_id, scenario, severity, score, entity_level, entity_id,
                entity_name, diagnosis_ar, evidence_json, recommended_action_ar
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                hit.get("scenario"),
                hit.get("severity"),
                hit.get("score"),
                hit.get("entity_level"),
                hit.get("entity_id"),
                hit.get("entity_name"),
                hit.get("diagnosis_ar"),
                json.dumps(hit.get("evidence", {}), ensure_ascii=False, default=str),
                hit.get("recommended_action_ar"),
            ),
        )
    con.commit()
    con.close()
    return run_id
