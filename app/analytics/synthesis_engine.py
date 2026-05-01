"""Multivariate synthesis layer for Meta Ads performance.

Combines three or more dimensions into deep, non-duplicative conclusions.
"""
from __future__ import annotations

from typing import Any, Dict, List
import pandas as pd


class MultivariateSynthesisEngine:
    def __init__(self, feature_df: pd.DataFrame, campaign_context: Dict[str, Any] | None = None):
        self.df = feature_df.copy() if feature_df is not None else pd.DataFrame()
        self.context = campaign_context or {}
        self.means = self.df.mean(numeric_only=True).to_dict() if not self.df.empty else {}

    def _value(self, *names: str) -> float:
        for name in names:
            if name in self.means:
                try:
                    return float(self.means.get(name) or 0)
                except Exception:
                    return 0.0
        return 0.0

    def _check(self, names: str | List[str], condition: str, threshold: float) -> bool:
        if isinstance(names, str):
            names = [names]
        val = self._value(*names)
        if condition == ">":
            return val > threshold
        if condition == "<":
            return val < threshold
        if condition == ">=":
            return val >= threshold
        if condition == "<=":
            return val <= threshold
        return False

    def synthesize(self) -> List[Dict[str, Any]]:
        insights: List[Dict[str, Any]] = []

        ctr_names = ["ctr_link", "link_ctr_calc", "outbound_ctr_calc", "ctr"]
        cvr_names = ["cvr_click_to_purchase", "purchase_rate", "signal_quality"]
        lpv_names = ["lpv_rate"]
        hook_names = ["hook_rate", "thumbstop_rate"]
        hold_names = ["hold_25", "hold_rate_50", "hold_rate_75"]

        # 1. Deadly gap: high interest, weak landing arrival, weak conversion.
        if self._check(ctr_names, ">", 0.015) and self._check(lpv_names, "<", 0.60) and self._check(cvr_names, "<", 0.01):
            insights.append({
                "type": "deadly_gap",
                "level": "critical",
                "title": "الفجوة القاتلة: جذب قوي وتسريب بعد النقرة",
                "synthesis": "الإعلان يجذب النقرات، لكن نسبة وصول الزوار لصفحة الهبوط أو تحويلهم ضعيفة. المشكلة ليست في جذب الانتباه فقط بل في ما يحدث بعد النقرة.",
                "root_cause": "مزيج محتمل من بطء الصفحة أو مشكلة تتبع أو عدم تطابق وعد الإعلان مع تجربة الهبوط.",
                "action": "ابدأ بإصلاح سرعة الصفحة والتتبع، ثم راجع تطابق الإعلان مع صفحة الهبوط قبل ضخ ميزانية إضافية.",
                "signals": {"ctr": self._value(*ctr_names), "lpv_rate": self._value(*lpv_names), "conversion_rate": self._value(*cvr_names)},
            })

        # 2. Audience erosion: frequency + CPM pressure + weak response.
        if self._check("frequency", ">", 2.2) and (self._check("cpm_delta", ">", 0) or self._check("cpm", ">", 0)) and self._check(ctr_names, "<", 0.015):
            insights.append({
                "type": "audience_erosion",
                "level": "warning",
                "title": "تآكل الشريحة: تكرار أعلى مع استجابة أضعف",
                "synthesis": "التكرار يرتفع بينما التفاعل لا يتحسن بما يكفي. هذا غالبًا يعني أن الجمهور الحالي بدأ يتشبع من نفس الرسالة.",
                "root_cause": "تشبع جمهور أو زاوية إبداعية مستهلكة أو مزاد أصبح أغلى على نفس الشريحة.",
                "action": "غيّر الزاوية الإبداعية أو وسّع الجمهور قبل زيادة الميزانية.",
                "signals": {"frequency": self._value("frequency"), "cpm": self._value("cpm"), "ctr": self._value(*ctr_names)},
            })

        # 3. High hook / low hold: video starts strong but loses meaning quickly.
        if self._check(hook_names, ">", 0.20) and self._check(hold_names, "<", 0.45) and self._check(cvr_names, "<", 0.02):
            insights.append({
                "type": "high_hook_low_hold",
                "level": "optimization",
                "title": "Hook قوي لكن الرسالة لا تحتفظ بالجمهور",
                "synthesis": "البداية تجذب الانتباه، لكن الاستمرار والتحويل ضعيفان. هذا يشير إلى فجوة بين أول 3 ثوانٍ والرسالة البيعية.",
                "root_cause": "Hook فضولي أو منفصل عن العرض الحقيقي، فيجذب مشاهدة لا تتحول إلى نية شراء.",
                "action": "اجعل بداية الفيديو مرتبطة مباشرة بالمشكلة والمنتج، حتى لو انخفض الـ hook قليلًا سيرتفع التحويل النوعي.",
                "signals": {"hook": self._value(*hook_names), "hold": self._value(*hold_names), "conversion_rate": self._value(*cvr_names)},
            })

        return insights


def _dedupe_synthesis(items: List[Dict[str, Any]], limit: int = 5) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for item in items:
        key = item.get("type") or item.get("title")
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def build_deep_multivariate_analysis(feature_df: pd.DataFrame, campaign_context: Dict[str, Any] | None = None, limit: int = 5) -> List[Dict[str, Any]]:
    engine = MultivariateSynthesisEngine(feature_df, campaign_context)
    return _dedupe_synthesis(engine.synthesize(), limit=limit)
