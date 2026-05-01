import asyncio
import pandas as pd

from app.api import campaign_analysis as ca


class Body:
    account_id = 'act_123'
    campaign_id = 'cmp_1'
    since = '2026-04-01'
    until = '2026-04-03'
    date_preset = None
    compare_since = None
    compare_until = None
    level = 'ad'
    question = 'حلل الحملة'
    fields = None
    deep = False


def test_campaign_endpoint_flow_uses_live_fetch_pipeline(monkeypatch=None):
    calls = {'meta': 0, 'fetch': 0}

    def fake_meta_call(method, path, token, params=None):
        calls['meta'] += 1
        return {'id': 'cmp_1', 'name': 'Lead Campaign', 'objective': 'LEAD_GENERATION', 'status': 'ACTIVE'}

    def fake_fetch(account_id, token, level, fields, date_preset, since, until, filters, sort=None, time_increment=None):
        calls['fetch'] += 1
        return pd.DataFrame([
            {'date': '2026-04-01', 'campaign_id': 'cmp_1', 'ad_id': 'ad1', 'objective': 'LEAD_GENERATION', 'spend': 100, 'impressions': 10000, 'reach': 8000, 'frequency': 1.2, 'inline_link_clicks': 120, 'outbound_clicks': 90, 'actions': [{'action_type': 'lead', 'value': '8'}], 'action_values': [], 'cost_per_action_type': []},
            {'date': '2026-04-02', 'campaign_id': 'cmp_1', 'ad_id': 'ad1', 'objective': 'LEAD_GENERATION', 'spend': 120, 'impressions': 11000, 'reach': 8200, 'frequency': 1.5, 'inline_link_clicks': 110, 'outbound_clicks': 80, 'actions': [{'action_type': 'lead', 'value': '7'}], 'action_values': [], 'cost_per_action_type': []},
            {'date': '2026-04-03', 'campaign_id': 'cmp_1', 'ad_id': 'ad1', 'objective': 'LEAD_GENERATION', 'spend': 150, 'impressions': 12000, 'reach': 8300, 'frequency': 1.8, 'inline_link_clicks': 100, 'outbound_clicks': 70, 'actions': [{'action_type': 'lead', 'value': '6'}], 'action_values': [], 'cost_per_action_type': []},
        ])

    ca.meta_call = fake_meta_call
    ca.fetch_insights_df = fake_fetch
    result = asyncio.run(ca.analyze_campaign(Body(), token='fake'))
    assert calls['meta'] == 1
    assert calls['fetch'] >= 1
    assert result['source'] == 'meta_api_live_campaign_fetch'
    assert result['campaign_type'] == 'leads'
    assert result['run_id']
    assert result['result']['rows'] == 3
    assert 'report_markdown' in result['result']
