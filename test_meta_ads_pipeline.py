import json
from pathlib import Path

import pandas as pd

from app.analytics.semantic_metrics import expand_semantic_metrics
from app.analytics.analysis_pipeline import analyze_dataframe
from app.analytics.report_builder import build_skipped_sections


def sample_df():
    return pd.DataFrame([
        {
            'date': '2026-04-01',
            'campaign_id': 'c1',
            'campaign_name': 'Messages campaign',
            'spend': 100,
            'impressions': 10000,
            'reach': 8000,
            'frequency': 1.2,
            'inline_link_clicks': 120,
            'outbound_clicks': 80,
            'actions': json.dumps([
                {'action_type': 'onsite_conversion.messaging_conversation_started_7d', 'value': '15'},
                {'action_type': 'lead', 'value': '3'},
            ]),
            'action_values': json.dumps([]),
            'cost_per_action_type': json.dumps([
                {'action_type': 'onsite_conversion.messaging_conversation_started_7d', 'value': '6.66'}
            ]),
        },
        {
            'date': '2026-04-02',
            'campaign_id': 'c1',
            'campaign_name': 'Messages campaign',
            'spend': 130,
            'impressions': 11000,
            'reach': 8100,
            'frequency': 1.5,
            'inline_link_clicks': 100,
            'outbound_clicks': 70,
            'actions': json.dumps([
                {'action_type': 'onsite_conversion.messaging_conversation_started_7d', 'value': '14'}
            ]),
            'action_values': json.dumps([]),
            'cost_per_action_type': json.dumps([]),
        },
    ])


def test_semantic_metrics_parse_json_strings():
    out = expand_semantic_metrics(sample_df())
    assert float(out['messaging_conversations'].sum()) == 29.0
    assert 'signal_quality' in out.columns


def test_messages_skip_website_funnel():
    out = expand_semantic_metrics(sample_df())
    skipped = build_skipped_sections(out, 'messages')
    assert any(s['section'] == 'website_funnel' for s in skipped)


def test_pipeline_runs_without_hallucinated_sections():
    result = analyze_dataframe(sample_df(), campaign_type='messages', question='حلل الرسائل')
    assert result['rows'] == 2
    assert 'report_markdown' in result
    assert any(s['section'] == 'website_funnel' for s in result['skipped_sections'])
    assert 'صفحة هبوط' in result['report_markdown'] or 'website_funnel' in result['report_markdown']
