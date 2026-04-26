"""Rules catalog loader.

Main source: app/analytics/rules_catalog.json.
Add new rules there to expand intelligence when metrics already exist.
"""
from __future__ import annotations

import json
from pathlib import Path


def load_rules_catalog() -> list[dict]:
    path = Path(__file__).with_name("rules_catalog.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


RULES_CATALOG = load_rules_catalog()
