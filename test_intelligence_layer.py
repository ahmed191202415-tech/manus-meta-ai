import pandas as pd
from app.analytics.intelligent_diagnostics import build_intelligence_diagnostics

cur = pd.DataFrame([
    {
        'ad_id': '1', 'ad_name': 'Test Creative', 'spend': 200,
        'impressions': 10000, 'reach': 2500, 'frequency': 4.0,
        'ctr': 0.005, 'cpm': 20, 'inline_link_clicks': 50,
        'outbound_clicks': [{'action_type': 'outbound_click', 'value': '50'}],
        'actions': [
            {'action_type': 'landing_page_view', 'value': '20'},
            {'action_type': 'purchase', 'value': '1'},
        ],
        'action_values': [{'action_type': 'purchase', 'value': '50'}],
        'video_p25': 500, 'video_p50': 100, 'objective': 'OUTCOME_SALES',
    }
])
prev = pd.DataFrame([
    {
        'ad_id': '1', 'ad_name': 'Test Creative', 'spend': 120,
        'impressions': 10000, 'reach': 3500, 'frequency': 2.5,
        'ctr': 0.012, 'cpm': 12, 'inline_link_clicks': 120,
        'outbound_clicks': [{'action_type': 'outbound_click', 'value': '120'}],
        'actions': [
            {'action_type': 'landing_page_view', 'value': '100'},
            {'action_type': 'purchase', 'value': '3'},
        ],
        'action_values': [{'action_type': 'purchase', 'value': '180'}],
        'video_p25': 1200, 'video_p50': 700, 'objective': 'OUTCOME_SALES',
    }
])
r = build_intelligence_diagnostics(cur, prev, 'ad', 10)
print('diagnostics_count=', r['diagnostics_count'])
for h in r['top_diagnostics']:
    print(h['scenario'], h['severity'], h['score'], h['evidence_ar'])
print('summary=', r['summary_ar'])
