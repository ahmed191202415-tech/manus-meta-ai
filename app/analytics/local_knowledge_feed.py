"""Local research feed loader for Meta Ads Intelligence.

This is the explicit bridge between the research files found on the user's
machine and the runtime analysis layer. It does not call external AI.
"""
from __future__ import annotations
from pathlib import Path
from functools import lru_cache
from typing import Any, Dict, List
import json


FEED_PATH = Path(__file__).parent / "knowledge_base" / "generated" / "local_meta_ads_intelligence_feed.json"


@lru_cache(maxsize=1)
def load_local_feed() -> Dict[str, Any]:
    try:
        return json.loads(FEED_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {
            "feed_version": "missing",
            "metric_aliases": {},
            "diagnostic_patterns": [],
            "relationship_templates": [],
            "breakdown_triggers": [],
            "reporting_principles": [],
        }


def feed_patterns() -> List[Dict[str, Any]]:
    return list(load_local_feed().get("diagnostic_patterns") or [])


def feed_breakdown_triggers() -> List[Dict[str, Any]]:
    return list(load_local_feed().get("breakdown_triggers") or [])


def feed_relationship_templates() -> List[Dict[str, Any]]:
    return list(load_local_feed().get("relationship_templates") or [])


def feed_principles() -> List[str]:
    return list(load_local_feed().get("reporting_principles") or [])
