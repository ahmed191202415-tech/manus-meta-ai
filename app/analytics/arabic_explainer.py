"""Arabic evidence and explanation helpers."""
from __future__ import annotations
from typing import Any, Optional


def pct_label(value: Optional[float]) -> str:
    if value is None:
        return 'غير متاح'
    return f'{value * 100:.1f}%'


def money_label(value: Any) -> str:
    try:
        return f'{float(value):.2f}'
    except Exception:
        return 'غير متاح'


def evidence_sentence(evidence: dict) -> str:
    parts = []
    mapping = {
        'frequency_change': 'تغير التكرار',
        'ctr_change': 'تغير CTR',
        'cpm_change': 'تغير CPM',
        'cpa_change': 'تغير CPA',
        'roas_change': 'تغير ROAS',
        'lpv_rate': 'معدل وصول الصفحة',
        'atc_rate': 'معدل إضافة للسلة',
        'checkout_to_purchase_rate': 'معدل الدفع إلى الشراء',
        'signal_quality': 'جودة الإشارة',
        'thumbstop_rate': 'معدل إيقاف التمرير',
        'hold_rate_50': 'معدل استمرار 50%',
    }
    for key, label in mapping.items():
        if key in evidence and evidence[key] is not None:
            val = evidence[key]
            if 'change' in key or 'rate' in key or 'quality' in key:
                parts.append(f'{label}: {pct_label(val)}')
            else:
                parts.append(f'{label}: {val}')
    return '، '.join(parts) if parts else 'لا توجد أدلة رقمية كافية.'
