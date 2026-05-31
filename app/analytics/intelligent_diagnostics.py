"""Meta Ads Intelligence diagnostics.

Builds on recovered project docs:
- phased pull
- semantic metrics
- relationship-based diagnosis
- dynamic Arabic explanations
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional
import pandas as pd

from app.analytics.semantic_metrics import aggregate_metrics, expand_semantic_metrics, safe_div
from app.analytics.statistics_engine import pct_change, severity_from_score
from app.analytics.arabic_explainer import evidence_sentence
from app.analytics.diagnostic_rules_catalog import RULES_CATALOG
from app.analytics.goal_context import build_goal_context


def _row_dict(df: pd.DataFrame, idx: int) -> Dict[str, Any]:
    return df.iloc[idx].to_dict() if df is not None and not df.empty else {}


def _metric(row: Dict[str, Any], key: str) -> float:
    try:
        return float(row.get(key, 0) or 0)
    except Exception:
        return 0.0


def _entity_key(row: Dict[str, Any], level: str) -> str:
    return str(row.get(f'{level}_id') or row.get('ad_id') or row.get('adset_id') or row.get('campaign_id') or 'ALL')


def _entity_name(row: Dict[str, Any], level: str) -> str:
    return str(row.get(f'{level}_name') or row.get('ad_name') or row.get('adset_name') or row.get('campaign_name') or _entity_key(row, level))


def _row_goal(row: Dict[str, Any]) -> str:
    value = str(row.get('optimization_goal') or row.get('objective') or '').lower()
    if any(item in value for item in ('message', 'conversation', 'whatsapp')):
        return 'messages'
    if 'lead' in value:
        return 'leads'
    if any(item in value for item in ('sale', 'purchase', 'conversion', 'catalog')):
        return 'sales'
    if any(item in value for item in ('traffic', 'link_click', 'landing')):
        return 'traffic'
    if any(item in value for item in ('awareness', 'reach', 'video', 'engagement')):
        return 'awareness_engagement'
    return 'unknown'


def _find_previous(prev_df: pd.DataFrame, level: str, entity_id: str) -> Dict[str, Any]:
    if prev_df is None or prev_df.empty:
        return {}
    id_col = f'{level}_id'
    if id_col not in prev_df.columns:
        return {}
    match = prev_df[prev_df[id_col].astype(str) == str(entity_id)]
    return match.iloc[0].to_dict() if not match.empty else {}


def _make_hit(rule_id: str, scenario: str, score: float, rule: dict, entity: dict, evidence: dict) -> Dict[str, Any]:
    severity = severity_from_score(score)
    return {
        'rule_id': rule_id,
        'scenario': scenario,
        'severity': severity,
        'score': round(float(score), 2),
        'entity_level': entity['level'],
        'entity_id': entity['id'],
        'entity_name': entity['name'],
        'diagnosis_ar': rule['meaning_ar'],
        'evidence': evidence,
        'evidence_ar': evidence_sentence(evidence),
        'recommended_action_ar': rule['recommended_action_ar'],
        'required_metrics': rule.get('required_metrics', []),
    }


def _diagnose_entity(row: Dict[str, Any], prev: Dict[str, Any], level: str) -> List[Dict[str, Any]]:
    entity = {'level': level, 'id': _entity_key(row, level), 'name': _entity_name(row, level)}
    hits: List[Dict[str, Any]] = []
    goal = _row_goal(row)
    sales_goal = goal in ('sales', 'unknown')

    freq_ch = pct_change(_metric(row, 'frequency'), _metric(prev, 'frequency'))
    ctr_ch = pct_change(_metric(row, 'ctr'), _metric(prev, 'ctr'))
    cpm_ch = pct_change(_metric(row, 'cpm'), _metric(prev, 'cpm'))
    cpa_ch = pct_change(_metric(row, 'cpa_purchase'), _metric(prev, 'cpa_purchase'))
    roas_ch = pct_change(_metric(row, 'roas_calc'), _metric(prev, 'roas_calc'))
    spend_ch = pct_change(_metric(row, 'spend'), _metric(prev, 'spend'))
    purchases_ch = pct_change(_metric(row, 'purchases'), _metric(prev, 'purchases'))

    rule = RULES_CATALOG[0]
    fatigue_score = 0
    if _metric(row, 'frequency') >= 3: fatigue_score += 20
    if freq_ch is not None and freq_ch > 0.15: fatigue_score += 20
    if ctr_ch is not None and ctr_ch < -0.15: fatigue_score += 25
    if cpm_ch is not None and cpm_ch > 0.10: fatigue_score += 15
    if cpa_ch is not None and cpa_ch > 0.15: fatigue_score += 10
    if roas_ch is not None and roas_ch < -0.15: fatigue_score += 10
    if fatigue_score >= 45:
        hits.append(_make_hit('R001', 'Creative Fatigue', fatigue_score, rule, entity, {
            'frequency': _metric(row, 'frequency'), 'frequency_change': freq_ch,
            'ctr_change': ctr_ch, 'cpm_change': cpm_ch,
            'cpa_change': cpa_ch, 'roas_change': roas_ch,
        }))

    rule = RULES_CATALOG[1]
    if level in ('campaign', 'adset') and _metric(row, 'frequency') >= 3.5 and ctr_ch is not None and ctr_ch < -0.10:
        hits.append(_make_hit('R002', 'Audience Saturation', 65, rule, entity, {
            'frequency': _metric(row, 'frequency'), 'ctr_change': ctr_ch, 'reach': _metric(row, 'reach')
        }))

    rule = RULES_CATALOG[2]
    if _metric(row, 'outbound_clicks_count') >= 20 and 0 < _metric(row, 'lpv_rate') < 0.60:
        hits.append(_make_hit('R003', 'Landing Page Friction', 70, rule, entity, {
            'outbound_clicks': _metric(row, 'outbound_clicks_count'), 'landing_page_views': _metric(row, 'landing_page_views'), 'lpv_rate': _metric(row, 'lpv_rate')
        }))

    rule = RULES_CATALOG[3]
    if sales_goal and _metric(row, 'landing_page_views') >= 20 and _metric(row, 'atc_rate') < 0.02 and _metric(row, 'purchases') == 0:
        hits.append(_make_hit('R004', 'Offer / Product Friction', 55, rule, entity, {
            'landing_page_views': _metric(row, 'landing_page_views'), 'add_to_cart': _metric(row, 'add_to_cart'), 'atc_rate': _metric(row, 'atc_rate')
        }))

    rule = RULES_CATALOG[4]
    if sales_goal and _metric(row, 'add_to_cart') >= 5 and _metric(row, 'purchases') == 0:
        hits.append(_make_hit('R005', 'Checkout Friction', 65, rule, entity, {
            'add_to_cart': _metric(row, 'add_to_cart'), 'initiate_checkout': _metric(row, 'initiate_checkout'), 'purchases': _metric(row, 'purchases'), 'checkout_to_purchase_rate': _metric(row, 'checkout_to_purchase_rate')
        }))

    rule = RULES_CATALOG[5]
    if sales_goal and spend_ch is not None and spend_ch > 0.20 and (purchases_ch is None or purchases_ch <= 0) and (cpa_ch is not None and cpa_ch > 0.15):
        hits.append(_make_hit('R006', 'Budget Waste', 75, rule, entity, {
            'spend_change': spend_ch, 'purchases_change': purchases_ch, 'cpa_change': cpa_ch, 'roas_change': roas_ch
        }))

    rule = RULES_CATALOG[6]
    if cpm_ch is not None and cpm_ch > 0.25 and ctr_ch is not None and ctr_ch < -0.10:
        hits.append(_make_hit('R007', 'Auction Pressure', 60, rule, entity, {
            'cpm_change': cpm_ch, 'ctr_change': ctr_ch, 'cpm': _metric(row, 'cpm')
        }))

    rule = RULES_CATALOG[7]
    if sales_goal and _metric(row, 'outbound_clicks_count') >= 30 and _metric(row, 'signal_quality') < 0.005:
        hits.append(_make_hit('R008', 'Weak Signal Quality', 70, rule, entity, {
            'outbound_clicks': _metric(row, 'outbound_clicks_count'), 'purchases': _metric(row, 'purchases'), 'signal_quality': _metric(row, 'signal_quality')
        }))

    rule = RULES_CATALOG[8]
    if sales_goal and _metric(row, 'purchases') >= 3 and _metric(row, 'roas_calc') >= 1.5 and _metric(row, 'frequency') < 3.5 and (ctr_ch is None or ctr_ch > -0.10) and (cpm_ch is None or cpm_ch < 0.20):
        hits.append(_make_hit('R009', 'Scale Candidate', 55, rule, entity, {
            'purchases': _metric(row, 'purchases'), 'roas': _metric(row, 'roas_calc'), 'frequency': _metric(row, 'frequency'), 'ctr_change': ctr_ch, 'cpm_change': cpm_ch
        }))

    rule = RULES_CATALOG[10]
    if _metric(row, 'impressions') >= 1000 and _metric(row, 'thumbstop_rate') > 0 and _metric(row, 'thumbstop_rate') < 0.10:
        hits.append(_make_hit('R011', 'Weak Hook / Thumbstop Problem', 58, rule, entity, {
            'impressions': _metric(row, 'impressions'), 'thumbstop_rate': _metric(row, 'thumbstop_rate')
        }))

    rule = RULES_CATALOG[11]
    if _metric(row, 'video_p25') >= 50 and 0 < _metric(row, 'hold_rate_50') < 0.45:
        hits.append(_make_hit('R012', 'Video Hold / Message Continuity Problem', 58, rule, entity, {
            'video_p25': _metric(row, 'video_p25'), 'video_p50': _metric(row, 'video_p50'), 'hold_rate_50': _metric(row, 'hold_rate_50'), 'hold_rate_75': _metric(row, 'hold_rate_75')
        }))

    if goal == 'messages' and _metric(row, 'spend') > 0 and _metric(row, 'messaging_conversations') == 0:
        rule = RULES_CATALOG[13]
        hits.append(_make_hit('R014', 'Message Campaign Conversation Friction', 65, rule, entity, {
            'spend': _metric(row, 'spend'), 'ctr': _metric(row, 'ctr'),
            'messaging_conversations': _metric(row, 'messaging_conversations'),
        }))

    return hits


def _objective_notes(df: pd.DataFrame) -> List[str]:
    goal_context = build_goal_context(df)
    notes = []
    warning = goal_context.get("warning")
    if warning:
        notes.append(warning)
    notes.extend(goal_context.get("analysis_guardrails", []))
    if df is None or df.empty or 'objective' not in df.columns:
        return list(dict.fromkeys(notes))
    objectives = sorted(set(str(x) for x in df['objective'].dropna().unique() if str(x)))[:8]
    for obj in objectives:
        low = obj.lower()
        if 'message' in low:
            notes.append('الحملة تبدو مرتبطة بالرسائل؛ ركّز على بدء المحادثة وجودة الرد وليس مسار الشراء فقط.')
        elif 'video' in low or 'awareness' in low or 'reach' in low:
            notes.append('الحملة تبدو محتوى/وعي؛ قياس الكرييتف والتكرار والاحتفاظ أهم من CPA فقط.')
        elif 'lead' in low:
            notes.append('الحملة تبدو Lead Gen؛ يجب تقييم تكلفة وجودة العميل المحتمل وليس عدد leads فقط.')
    return list(dict.fromkeys(notes))


def build_intelligence_diagnostics(current_df: pd.DataFrame, compare_df: pd.DataFrame, level: str = 'campaign', top_n: int = 10) -> Dict[str, Any]:
    goal_context = build_goal_context(current_df)
    current = aggregate_metrics(current_df, level)
    previous = aggregate_metrics(compare_df, level) if compare_df is not None and not compare_df.empty else pd.DataFrame()
    hits: List[Dict[str, Any]] = []

    for idx in range(len(current)):
        row = _row_dict(current, idx)
        prev = _find_previous(previous, level, _entity_key(row, level))
        hits.extend(_diagnose_entity(row, prev, level))

    hits = sorted(hits, key=lambda x: x.get('score', 0), reverse=True)
    scenario_counts: Dict[str, int] = {}
    for hit in hits:
        scenario_counts[hit['scenario']] = scenario_counts.get(hit['scenario'], 0) + 1

    top_hits = hits[:top_n]
    summary_ar = 'تم تحليل العلاقات بين الأرقام وليس الأرقام منفردة.'
    if top_hits:
        top = top_hits[0]
        summary_ar = f"أقوى تشخيص ظاهر: {top['scenario']} على {top['entity_name']} بدرجة {top['score']}. {top['diagnosis_ar']}"

    missing_notes = []
    required = sorted({m for rule in RULES_CATALOG for m in rule.get('required_metrics', [])})
    available = set(current.columns) if current is not None else set()
    missing = [m for m in required if m not in available]
    if missing:
        missing_notes.append('بعض المقاييس غير متاحة في السحب الحالي: ' + ', '.join(missing[:20]))

    return {
        'summary_ar': summary_ar,
        'entity_level': level,
        'entities_analyzed': int(len(current)) if current is not None else 0,
        'rules_available': len(RULES_CATALOG),
        'diagnostics_count': len(hits),
        'scenario_counts': scenario_counts,
        'top_diagnostics': top_hits,
        'goal_context': goal_context,
        'objective_notes': _objective_notes(current_df),
        'missing_notes': missing_notes,
        'method': {
            'source': 'Recovered Downloads content + project prompt + rules catalog',
            'principle': 'relationship between metrics + previous window + semantic action flattening',
            'no_external_ai': True,
        },
    }
