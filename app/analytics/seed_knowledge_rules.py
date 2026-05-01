"""Seed Supabase knowledge_rules from knowledge_base/rules_catalog_seed.json."""
from __future__ import annotations

import json
from pathlib import Path

import requests

from app.analytics import supabase_storage


def seed_rules(path: str | Path | None = None) -> int:
    if not supabase_storage.enabled():
        raise RuntimeError('Set INTELLIGENCE_STORAGE=supabase, SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY before seeding rules.')
    path = Path(path) if path else Path(__file__).parent / 'knowledge_base' / 'rules_catalog_seed.json'
    rules = json.loads(path.read_text(encoding='utf-8'))
    url = supabase_storage._endpoint('knowledge_rules', on_conflict='rule_key')
    response = requests.post(
        url,
        headers=supabase_storage._headers(),
        data=json.dumps(rules, ensure_ascii=False, default=str),
        timeout=90,
    )
    if response.status_code >= 400:
        raise RuntimeError(f'Failed to seed knowledge_rules: {response.status_code} {response.text[:1000]}')
    return len(rules)


if __name__ == '__main__':
    print(seed_rules())
