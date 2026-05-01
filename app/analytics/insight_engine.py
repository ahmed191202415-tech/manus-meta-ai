"""Human business insight layer for Meta Ads diagnostics.

This module translates statistical diagnostic edges/hits into clear Arabic
business insights. It is intentionally deterministic and local: no external AI.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Set


Condition = Callable[[str, str, str, float], bool]


INSIGHT_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "fatigue": {
        "condition": lambda s, t, r, w: ("frequency" in s and ("ctr" in t or "click" in t)) or (("ctr" in s or "click" in s) and "frequency" in t) or "fatigue" in r.lower(),
        "title": "إرهاق المحتوى الإعلاني (Ad Fatigue)",
        "meaning": "نلاحظ علاقة سلبية بين تكرار ظهور الإعلان واستجابة الجمهور. الجمهور بدأ يتجاهل الإعلان بسبب كثرة رؤيته أو ضعف تجديد الزاوية الإبداعية.",
        "action": "غيّر التصميم أو زاوية الرسالة، ووسّع الاستهداف أو افصل الشرائح المتعبة قبل زيادة الميزانية.",
    },
    "landing_leak": {
        "condition": lambda s, t, r, w: ("click" in s and "lpv" in t) or ("lpv" in s and "click" in t) or "landing" in r.lower(),
        "title": "تسريب في صفحة الهبوط (Landing Page Leak)",
        "meaning": "هناك فجوة بين النقرات والوصول الفعلي لصفحة الهبوط. السبب المحتمل بطء الصفحة، مشكلة تتبع، أو عدم توافق تجربة الصفحة مع الإعلان.",
        "action": "افحص سرعة الصفحة، Pixel/CAPI، ورابط الهبوط، وقارن بين outbound clicks و landing page views.",
    },
    "low_intent": {
        "condition": lambda s, t, r, w: ("ctr" in s and ("cvr" in t or "purchase" in t)) or (("cvr" in s or "purchase" in s) and "ctr" in t) or "intent" in r.lower(),
        "title": "نقرات جذابة لكنها ضعيفة النية",
        "meaning": "الإعلان يجذب الانتباه، لكن الزوار لا يكملون التحويل. قد يكون الوعد الإعلاني أقوى من العرض الفعلي أو صفحة الهبوط لا تكمّل نفس الرسالة.",
        "action": "راجع تطابق الإعلان مع صفحة الهبوط والعرض والسعر، وقلل وعود الفضول غير المرتبطة بالشراء.",
    },
    "auction_pressure": {
        "condition": lambda s, t, r, w: "cpm" in s or "cpm" in t or "auction" in r.lower(),
        "title": "ضغط مزاد وارتفاع تكلفة الوصول",
        "meaning": "التكلفة ترتفع على مستوى المزاد، وقد يكون السبب جمهور محدود، منافسة أعلى، أو انخفاض جودة الإعلان.",
        "action": "لا ترفع الميزانية مباشرة؛ اختبر جمهورًا أوسع أو زاوية إبداعية جديدة لتحسين جودة المزاد.",
    },
    "segment_winner": {
        "condition": lambda s, t, r, w: r == "segment_deviation" and w > 0,
        "title": "فرصة نمو في شريحة محددة",
        "meaning": "أداء الشريحة {segment_val} يتفوق بوضوح على المتوسط العام للحملة.",
        "action": "زِد وزن هذه الشريحة أو أنشئ حملة مخصصة لها مع الحفاظ على قياس CPA/ROAS.",
    },
}


def _edge_from_diagnostic(hit: Dict[str, Any]) -> Dict[str, Any]:
    evidence = hit.get("evidence", {}) or {}
    keys = list(evidence.keys())
    source = keys[0] if keys else hit.get("scenario", "diagnostic")
    target = keys[1] if len(keys) > 1 else hit.get("entity_level", "performance")
    return {
        "source": source,
        "target": target,
        "relation_type": hit.get("scenario", "diagnostic"),
        "weight": hit.get("score", 0),
        "confidence": min(float(hit.get("score", 0) or 0) / 100.0, 1.0),
        "context": {
            "entity_name": hit.get("entity_name"),
            "entity_id": hit.get("entity_id"),
            "segment_value": hit.get("entity_name"),
        },
    }


def translate_edge_to_insight(edge: Dict[str, Any]) -> Dict[str, Any]:
    source = str(edge.get("source", "")).lower()
    target = str(edge.get("target", "")).lower()
    relation = str(edge.get("relation_type", ""))
    weight = float(edge.get("weight", 0) or 0)
    context = edge.get("context", {}) or {}

    for key, template in INSIGHT_TEMPLATES.items():
        if template["condition"](source, target, relation, weight):
            meaning = template["meaning"]
            if "{segment_val}" in meaning:
                meaning = meaning.format(segment_val=context.get("segment_value", ""))
            return {
                "type": key,
                "title": template["title"],
                "meaning": meaning,
                "action": template["action"],
                "confidence": edge.get("confidence", 0),
                "source_edge": edge,
            }

    return {
        "type": "general_observation",
        "title": "ملاحظة إحصائية عامة",
        "meaning": f"هناك علاقة بين {source} و {target} تستحق المتابعة لأنها قد تؤثر على القرار الإعلاني.",
        "action": "راقب استقرار هذه العلاقة خلال 48 ساعة، ولا تتخذ قرارًا كبيرًا من قراءة واحدة فقط.",
        "confidence": edge.get("confidence", 0),
        "source_edge": edge,
    }


def build_human_insights(top_edges: List[Dict[str, Any]], limit: int = 5) -> List[Dict[str, Any]]:
    insights: List[Dict[str, Any]] = []
    seen_types: Set[str] = set()
    for edge in top_edges:
        insight = translate_edge_to_insight(edge)
        key = insight.get("type", "general_observation")
        if key not in seen_types or key == "general_observation":
            insights.append(insight)
            seen_types.add(key)
        if len(insights) >= limit:
            break
    return insights


def build_human_insights_from_diagnostics(top_diagnostics: List[Dict[str, Any]], limit: int = 5) -> List[Dict[str, Any]]:
    """Compatibility bridge: current project returns diagnostics, not graph edges."""
    edges = [_edge_from_diagnostic(hit) for hit in top_diagnostics]
    return build_human_insights(edges, limit=limit)
