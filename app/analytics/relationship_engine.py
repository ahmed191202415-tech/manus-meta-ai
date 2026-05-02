"""Relationship discovery for Meta Ads metrics.

Produces deterministic relationship edges for binary and ternary Meta Ads
relationships. The goal is not to overfit, but to surface enough useful
relationships for Arabic diagnosis even when some Meta fields are missing.
"""
from __future__ import annotations

from typing import Any, Dict, List
import pandas as pd
import numpy as np


def _numeric(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(df[col], errors='coerce')


def _first_col(df: pd.DataFrame, names: list[str]) -> str | None:
    for name in names:
        if name in df.columns and _numeric(df, name).notna().sum() >= 3 and _numeric(df, name).nunique(dropna=True) >= 2:
            return name
    return None


def _corr(df: pd.DataFrame, a: str, b: str) -> float:
    if a not in df.columns or b not in df.columns:
        return 0.0
    x = _numeric(df, a)
    y = _numeric(df, b)
    clean = pd.concat([x, y], axis=1).dropna()
    if len(clean) < 3 or clean.iloc[:, 0].nunique() < 2 or clean.iloc[:, 1].nunique() < 2:
        return 0.0
    value = clean.iloc[:, 0].corr(clean.iloc[:, 1])
    return 0.0 if pd.isna(value) else float(value)


def _confidence(weight: float, n: int) -> str:
    w = abs(weight)
    if n < 5:
        return 'low'
    if w >= 0.65 and n >= 8:
        return 'high'
    if w >= 0.30:
        return 'medium'
    return 'low'


def _explain(a: str, b: str, c: float) -> str:
    if a == 'frequency' and b in {'ctr_link', 'link_ctr_calc', 'outbound_ctr', 'outbound_ctr_calc', 'ctr'} and c < 0:
        return 'كلما زاد التكرار انخفض التفاعل؛ هذا يقوي احتمال إجهاد المحتوى أو تشبع الجمهور.'
    if a == 'frequency' and b in {'cpa', 'cost_per_result', 'cost_per_purchase'} and c > 0:
        return 'زيادة التكرار مرتبطة بارتفاع تكلفة النتيجة؛ التوسع الحالي قد يستهلك جمهورًا متشبعًا.'
    if a == 'cpm' and b in {'ctr_link', 'link_ctr_calc', 'ctr'} and c < 0:
        return 'تكلفة الظهور ترتفع بينما الضغط يضعف؛ هذا قد يشير إلى ضغط مزاد أو جودة إعلان أقل.'
    if a in {'link_clicks', 'inline_link_clicks'} and b == 'results' and c > 0:
        return 'الضغطات تتحرك مع النتائج؛ يوجد قدر من النية وليس مجرد فضول فقط.'
    if a in {'outbound_ctr', 'outbound_ctr_calc'} and b == 'lpv_rate' and c < 0:
        return 'النقرات الخارجة لا تتحول إلى وصول فعلي؛ افحص سرعة الصفحة أو التتبع أو ملاءمة الوجهة.'
    if a in {'outbound_ctr', 'outbound_ctr_calc'} and b == 'signal_quality' and c < 0:
        return 'النقرات الخارجة لا تتحول إلى إشارات مفيدة؛ احتمال فضول بلا نية أو مشكلة بعد الضغط.'
    if a == 'spend' and b == 'results' and c <= 0:
        return 'زيادة الإنفاق لا ترتبط بزيادة النتائج؛ افحص الهدر أو ضعف العائد الحدّي.'
    if a == 'spend' and b == 'results' and c > 0:
        return 'زيادة الإنفاق مرتبطة بزيادة النتائج؛ يجب قياس هل الكفاءة ثابتة أم أن العائد الحدّي يضعف.'
    direction = 'موجبة' if c > 0 else 'عكسية'
    return f'العلاقة بين {a} و {b} {direction} ووزنها {c:.3f}.'


def _add_edge(edges: list[dict[str, Any]], df: pd.DataFrame, a: str, b: str, relation_type: str, min_abs: float = 0.18) -> None:
    n = len(df)
    w = _corr(df, a, b)
    if abs(w) >= min_abs:
        edges.append({
            'source_metric': a,
            'target_metric': b,
            'relation_type': relation_type,
            'weight': round(w, 4),
            'confidence': _confidence(w, n),
            'explanation_ar': _explain(a, b, w),
            'evidence': {'rows': n, 'type': 'binary_correlation'},
        })


def _ternary_edges(df: pd.DataFrame) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    n = len(df)
    if n < 3:
        return edges

    ctr = _first_col(df, ['link_ctr_calc', 'ctr_link', 'ctr'])
    result = _first_col(df, ['results', 'messaging_conversations', 'leads', 'purchases'])
    spend = _first_col(df, ['spend'])
    freq = _first_col(df, ['frequency'])
    cpm = _first_col(df, ['cpm'])
    clicks = _first_col(df, ['link_clicks', 'inline_link_clicks', 'outbound_clicks_count'])

    def mean(col: str | None) -> float:
        if not col:
            return 0.0
        s = _numeric(df, col).replace([np.inf, -np.inf], np.nan).dropna()
        return float(s.mean()) if len(s) else 0.0

    # Three-number scenario: spend + clicks + results.
    if spend and clicks and result:
        r_spend_clicks = _corr(df, spend, clicks)
        r_clicks_results = _corr(df, clicks, result)
        r_spend_results = _corr(df, spend, result)
        if abs(r_spend_clicks) >= 0.18 and abs(r_clicks_results) >= 0.18:
            edges.append({
                'source_metric': f'{spend}+{clicks}',
                'target_metric': result,
                'relation_type': 'spend_clicks_results_triangle',
                'weight': round((abs(r_spend_clicks) + abs(r_clicks_results) + abs(r_spend_results)) / 3, 4),
                'confidence': _confidence((abs(r_spend_clicks) + abs(r_clicks_results)) / 2, n),
                'explanation_ar': 'العلاقة الثلاثية بين الإنفاق والضغطات والنتائج توضح هل الإنفاق يشتري نية حقيقية أم مجرد تفاعل.',
                'evidence': {'rows': n, 'type': 'ternary', 'spend_clicks': round(r_spend_clicks, 4), 'clicks_results': round(r_clicks_results, 4), 'spend_results': round(r_spend_results, 4)},
            })

    # Content fatigue scenario: frequency + CTR + CPM.
    if freq and ctr and cpm:
        r_freq_ctr = _corr(df, freq, ctr)
        r_cpm_ctr = _corr(df, cpm, ctr)
        if abs(r_freq_ctr) >= 0.18 or abs(r_cpm_ctr) >= 0.18:
            scenario = 'إشارة إجهاد محتوى/ضغط مزاد' if (r_freq_ctr < 0 or r_cpm_ctr < 0) else 'التفاعل لا ينهار مع التكرار/المزاد'
            edges.append({
                'source_metric': f'{freq}+{cpm}',
                'target_metric': ctr,
                'relation_type': 'frequency_cpm_ctr_triangle',
                'weight': round((abs(r_freq_ctr) + abs(r_cpm_ctr)) / 2, 4),
                'confidence': _confidence((abs(r_freq_ctr) + abs(r_cpm_ctr)) / 2, n),
                'explanation_ar': f'{scenario}: تم فحص التكرار وتكلفة الظهور مع معدل الضغط لتقييم إجهاد المحتوى أو ضغط المزاد.',
                'evidence': {'rows': n, 'type': 'ternary', 'frequency_ctr': round(r_freq_ctr, 4), 'cpm_ctr': round(r_cpm_ctr, 4), 'avg_frequency': round(mean(freq), 4), 'avg_cpm': round(mean(cpm), 4), 'avg_ctr': round(mean(ctr), 6)},
            })
    return edges


def discover_relationship_edges(df: pd.DataFrame) -> List[Dict[str, Any]]:
    if df is None or df.empty:
        return []

    # Create aliases so the engine works with actual semantic column names.
    work = df.copy()
    if 'ctr_link' not in work.columns and 'link_ctr_calc' in work.columns:
        work['ctr_link'] = work['link_ctr_calc']
    if 'outbound_ctr' not in work.columns and 'outbound_ctr_calc' in work.columns:
        work['outbound_ctr'] = work['outbound_ctr_calc']
    if 'results' not in work.columns and 'messaging_conversations' in work.columns:
        work['results'] = work['messaging_conversations']
    if 'cpa' not in work.columns and 'spend' in work.columns and 'results' in work.columns:
        res = pd.to_numeric(work['results'], errors='coerce').replace(0, np.nan)
        work['cpa'] = pd.to_numeric(work['spend'], errors='coerce') / res

    pairs = [
        ('frequency', 'ctr_link', 'frequency_vs_ctr'),
        ('frequency', 'outbound_ctr', 'frequency_vs_outbound'),
        ('frequency', 'results', 'frequency_vs_results'),
        ('frequency', 'cpa', 'frequency_vs_cpa'),
        ('cpm', 'ctr_link', 'auction_vs_ctr'),
        ('cpm', 'results', 'auction_vs_results'),
        ('cpc', 'results', 'click_cost_vs_results'),
        ('link_clicks', 'results', 'clicks_vs_results'),
        ('inline_link_clicks', 'results', 'inline_clicks_vs_results'),
        ('outbound_clicks_count', 'results', 'outbound_clicks_vs_results'),
        ('outbound_ctr', 'lpv_rate', 'click_to_landing'),
        ('outbound_ctr', 'signal_quality', 'click_intent_vs_signal'),
        ('spend', 'results', 'spend_vs_results'),
        ('spend', 'link_clicks', 'spend_vs_clicks'),
        ('spend', 'impressions', 'spend_vs_impressions'),
        ('spend', 'reach', 'spend_vs_reach'),
        ('spend', 'cpa', 'spend_vs_cpa'),
        ('impressions', 'results', 'impressions_vs_results'),
        ('reach', 'results', 'reach_vs_results'),
        ('roas', 'spend', 'roas_vs_spend'),
    ]

    edges: List[Dict[str, Any]] = []
    for a, b, relation_type in pairs:
        _add_edge(edges, work, a, b, relation_type, min_abs=0.18)

    edges.extend(_ternary_edges(work))

    # Sort strongest first and de-duplicate relation types.
    seen = set()
    unique = []
    for edge in sorted(edges, key=lambda e: abs(float(e.get('weight') or 0)), reverse=True):
        key = edge.get('relation_type')
        if key in seen:
            continue
        seen.add(key)
        unique.append(edge)
    return unique[:12]
