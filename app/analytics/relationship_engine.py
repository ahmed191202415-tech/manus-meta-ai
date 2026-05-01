"""Relationship discovery for Meta Ads metrics.

Produces deterministic relationship edges that can be translated by insight_engine
and combined by synthesis_engine.
"""
from __future__ import annotations

from typing import Any, Dict, List
import pandas as pd


def _corr(df: pd.DataFrame, a: str, b: str) -> float:
    if a not in df.columns or b not in df.columns:
        return 0.0
    x = pd.to_numeric(df[a], errors='coerce')
    y = pd.to_numeric(df[b], errors='coerce')
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
    if w >= 0.35:
        return 'medium'
    return 'low'


def _explain(a: str, b: str, c: float) -> str:
    if a == 'frequency' and b in {'ctr_link', 'outbound_ctr'} and c < 0:
        return 'كلما زاد التكرار انخفض التفاعل؛ هذا يقوي احتمال إجهاد المحتوى أو تشبع الجمهور.'
    if a == 'frequency' and b in {'cpa', 'cost_per_purchase'} and c > 0:
        return 'زيادة التكرار مرتبطة بارتفاع تكلفة النتيجة؛ التوسع الحالي قد يستهلك جمهورًا متشبعًا.'
    if a == 'cpm' and b == 'ctr_link' and c < 0:
        return 'تكلفة الظهور ترتفع بينما الضغط يضعف؛ هذا قد يشير إلى ضغط مزاد أو جودة إعلان أقل.'
    if a == 'outbound_ctr' and b == 'lpv_rate' and c < 0:
        return 'النقرات الخارجة لا تتحول إلى وصول فعلي؛ افحص سرعة الصفحة أو التتبع أو ملاءمة الوجهة.'
    if a == 'outbound_ctr' and b == 'signal_quality' and c < 0:
        return 'النقرات الخارجة لا تتحول إلى إشارات مفيدة؛ احتمال فضول بلا نية أو مشكلة بعد الضغط.'
    if a == 'spend' and b == 'results' and c <= 0:
        return 'زيادة الإنفاق لا ترتبط بزيادة النتائج؛ افحص الهدر أو ضعف العائد الحدّي.'
    direction = 'موجبة' if c > 0 else 'عكسية'
    return f'العلاقة بين {a} و {b} {direction} ووزنها {c:.3f}.'


def discover_relationship_edges(df: pd.DataFrame) -> List[Dict[str, Any]]:
    if df is None or df.empty:
        return []
    pairs = [
        ('frequency', 'ctr_link', 'frequency_vs_ctr'),
        ('frequency', 'outbound_ctr', 'frequency_vs_outbound'),
        ('frequency', 'cpa', 'frequency_vs_cpa'),
        ('frequency', 'cost_per_purchase', 'frequency_vs_purchase_cost'),
        ('cpm', 'ctr_link', 'auction_vs_ctr'),
        ('outbound_ctr', 'lpv_rate', 'click_to_landing'),
        ('outbound_ctr', 'signal_quality', 'click_intent_vs_signal'),
        ('spend', 'results', 'spend_vs_results'),
        ('spend', 'cpa', 'spend_vs_cpa'),
        ('roas', 'spend', 'roas_vs_spend'),
    ]
    n = len(df)
    edges: List[Dict[str, Any]] = []
    for a, b, relation_type in pairs:
        w = _corr(df, a, b)
        if abs(w) >= 0.25:
            edges.append({
                'source_metric': a,
                'target_metric': b,
                'relation_type': relation_type,
                'weight': round(w, 4),
                'confidence': _confidence(w, n),
                'explanation_ar': _explain(a, b, w),
                'evidence': {'rows': n},
            })
    return edges
