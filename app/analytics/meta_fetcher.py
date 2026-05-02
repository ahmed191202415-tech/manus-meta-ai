"""Progressive Meta Marketing API fetch plan.

The analyzer can work from local exports. This module defines the production
fetch policy: basic light pull first, then breakdowns only when requested or
when diagnostics need them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

BASIC_FIELDS = [
    'date_start', 'date_stop', 'account_id', 'campaign_id', 'campaign_name',
    'adset_id', 'adset_name', 'ad_id', 'ad_name', 'objective',
    'spend', 'impressions', 'reach',
    'frequency', 'clicks', 'inline_link_clicks', 'outbound_clicks', 'actions',
    'action_values', 'cost_per_action_type', 'cpm', 'cpc', 'ctr',
    'quality_ranking', 'engagement_rate_ranking', 'conversion_rate_ranking',
]

DEEP_BREAKDOWNS = {
    'placement': ['publisher_platform', 'platform_position'],
    'device': ['impression_device'],
    'country': ['country'],
    'age_gender': ['age', 'gender'],
    'hour': ['hourly_stats_aggregated_by_advertiser_time_zone'],
}

@dataclass
class FetchPlan:
    level: str = 'ad'
    fields: List[str] = field(default_factory=lambda: BASIC_FIELDS.copy())
    time_increment: int = 1
    breakdowns: List[str] = field(default_factory=list)
    action_breakdowns: List[str] = field(default_factory=lambda: ['action_type'])
    phase: str = 'basic'
    reason: str = 'basic light pull'


def build_basic_fetch_plan(level: str = 'ad') -> FetchPlan:
    return FetchPlan(level=level)


def build_deep_fetch_plan(reason: str, breakdown_key: str, level: str = 'ad') -> FetchPlan:
    return FetchPlan(
        level=level,
        breakdowns=DEEP_BREAKDOWNS.get(breakdown_key, []),
        phase='deep_breakdown',
        reason=reason,
    )


def recommend_breakdowns(question: str = '', diagnostics: Optional[List[Dict]] = None) -> List[FetchPlan]:
    q = (question or '').lower()
    diagnostics = diagnostics or []
    plans: List[FetchPlan] = []
    if any(word in q for word in ['موضع', 'مواضع', 'placement', 'مكان الظهور']):
        plans.append(build_deep_fetch_plan('user asked for placement detail', 'placement'))
    if any(word in q for word in ['جهاز', 'أجهزة', 'اجهزة', 'device', 'موبايل', 'desktop']):
        plans.append(build_deep_fetch_plan('user asked for device detail', 'device'))
    if any(word in q for word in ['دولة', 'دول', 'country', 'منطقة', 'مناطق', 'بلد']):
        plans.append(build_deep_fetch_plan('user asked for country detail', 'country'))
    if any(word in q for word in ['سن', 'نوع', 'عمر', 'جنس', 'age', 'gender']):
        plans.append(build_deep_fetch_plan('user asked for demographic detail', 'age_gender'))
    if any(word in q for word in ['ساعة', 'ساعات', 'وقت', 'أوقات', 'اوقات', 'hour']):
        plans.append(build_deep_fetch_plan('user asked for hourly detail', 'hour'))
    if any(word in q for word in ['جمهور', 'audience', 'شريحة', 'شرائح']):
        plans.append(build_deep_fetch_plan('user asked for audience detail', 'age_gender'))
        plans.append(build_deep_fetch_plan('user asked for location detail', 'country'))
    if any(word in q for word in ['ميزانية', 'budget', 'صرف', 'انفاق', 'إنفاق', 'توسع', 'scale']):
        plans.append(build_deep_fetch_plan('budget detail needs placement/device split', 'placement'))
        plans.append(build_deep_fetch_plan('budget detail needs device split', 'device'))
    for d in diagnostics:
        fam = str(d.get('family') or d.get('scenario') or d.get('code') or '').lower()
        if 'saturation' in fam or 'تشبع' in fam:
            plans.append(build_deep_fetch_plan('audience saturation needs demographic or placement split', 'age_gender'))
        if 'landing' in fam or 'تسريب' in fam:
            plans.append(build_deep_fetch_plan('post-click leak may be device specific', 'device'))
        if 'waste' in fam or 'هدر' in fam:
            plans.append(build_deep_fetch_plan('budget waste needs placement split', 'placement'))
    # de-duplicate by breakdown tuple
    unique = []
    seen = set()
    for plan in plans:
        key = tuple(plan.breakdowns)
        if key not in seen:
            unique.append(plan)
            seen.add(key)
    return unique
