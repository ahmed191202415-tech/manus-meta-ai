"""Dynamic Arabic reporting for Meta Ads intelligence."""
from __future__ import annotations

from typing import Any, Dict, List


def _fmt_pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.2f}%"
    except Exception:
        return "غير متاح"


def _fmt_num(value: Any) -> str:
    try:
        return f"{float(value):,.2f}"
    except Exception:
        return "غير متاح"


def allowed_sections_for_campaign(campaign_type: str) -> Dict[str, bool]:
    c = (campaign_type or 'unknown').lower()
    return {
        'website_funnel': c in {'sales', 'traffic', 'unknown'},
        'purchase_value': c in {'sales', 'unknown'},
        'lead_form': c in {'leads', 'unknown'},
        'messages': c in {'messages', 'unknown'},
        'video_awareness': c in {'awareness', 'video', 'unknown'},
        'app': c in {'app', 'unknown'},
    }


def build_skipped_sections(df, campaign_type: str) -> List[Dict[str, Any]]:
    allowed = allowed_sections_for_campaign(campaign_type)
    skipped: List[Dict[str, Any]] = []
    if not allowed['website_funnel']:
        skipped.append({'section': 'website_funnel', 'reason': 'نوع الحملة لا يسمح بافتراض صفحة هبوط أو سلة أو دفع.', 'required_fields': ['landing_page_views', 'purchases']})
    if not allowed['purchase_value']:
        skipped.append({'section': 'purchase_value', 'reason': 'نوع الحملة لا يسمح بحكم شراء/ROAS بدون أحداث وقيمة.', 'required_fields': ['purchase_value', 'purchases']})
    if allowed['website_funnel']:
        for section, fields in {'landing_page': ['outbound_clicks', 'landing_page_views'], 'checkout': ['add_to_cart', 'initiate_checkout'], 'purchase': ['purchases', 'purchase_value']}.items():
            missing = [f for f in fields if f not in getattr(df, 'columns', [])]
            if missing:
                skipped.append({'section': section, 'reason': 'بيانات المسار غير مكتملة.', 'required_fields': missing})
    return skipped


def build_dynamic_report_ar(result: Dict[str, Any], campaign_type: str = 'unknown', question: str = '') -> str:
    rows = result.get('rows', 0)
    metrics = result.get('metrics', {}) or {}
    diagnostics = result.get('diagnostics', []) or []
    statistical_profile = result.get('statistical_profile', {}) or {}
    human_insights = result.get('human_insights', []) or []
    synthesis = result.get('multivariate_synthesis', []) or []
    relationships = result.get('relationships', []) or []
    skipped = result.get('skipped_sections', []) or []
    deep_breakdowns = result.get('deep_breakdown_results', []) or []
    deep_plans = result.get('deep_fetch_plans', []) or []

    lines: List[str] = ['# تقرير Meta Ads Intelligence', '']
    if question:
        lines.append(f'**سؤال المستخدم:** {question}')
    lines.append(f'**نوع الحملة:** {campaign_type or "غير محدد"}')
    lines.append(f'**حجم البيانات:** {rows} صف')
    lines.append('')
    lines.append('## الملخص السريع')
    if rows == 0:
        lines.append('لا توجد بيانات كافية للتحليل.')
        return '\n'.join(lines)
    lines.append(result.get('summary_ar') or 'تم تحليل البيانات عبر المقاييس والعلاقات والتشخيصات المتاحة بدون افتراض أقسام غير مدعومة.')
    if metrics:
        core = []
        for key in ['spend', 'impressions', 'reach', 'frequency', 'ctr_link', 'outbound_ctr', 'cpa', 'roas', 'signal_quality']:
            if key in metrics:
                val = _fmt_pct(metrics[key]) if key in {'ctr_link', 'outbound_ctr', 'signal_quality'} else _fmt_num(metrics[key])
                core.append(f'{key}: {val}')
        if core:
            lines.append('- ' + ' | '.join(core[:9]))
    lines.append('')

    if relationships:
        lines.append('## العلاقات المكتشفة')
        for edge in relationships[:8]:
            lines.append(f"- **{edge.get('relation_type','علاقة')}**: {edge.get('explanation_ar','')} (الثقة: {edge.get('confidence','غير محددة')}, الوزن: {edge.get('weight','')})")
        lines.append('')


    if statistical_profile:
        lines.append('## الطبقة الإحصائية قبل التشخيص')
        ss = statistical_profile.get('sample_sufficiency', {})
        lines.append(f"- حجم العينة: {ss.get('rows', statistical_profile.get('rows', 0))} صف، أيام: {ss.get('days', 0)}، المستوى: {ss.get('level', '')}")
        anomalies = statistical_profile.get('anomalies', []) or []
        lines.append(f"- الشذوذات المكتشفة: {len(anomalies)}")
        decisions = statistical_profile.get('decision_scores', []) or []
        if decisions:
            lines.append('- قرارات مبدئية حسب الإحصاء:')
            for d in decisions[:5]:
                name = d.get('ad_name') or d.get('adset_name') or d.get('campaign_name') or d.get('ad_id') or d.get('adset_id') or d.get('campaign_id') or ''
                lines.append(f"  - {name}: {d.get('decision')} score={_fmt_num(d.get('decision_score',0))}, results={_fmt_num(d.get('results',0))}, cpa={_fmt_num(d.get('cpa',0))}")
        trends = statistical_profile.get('trends', {}) or {}
        important = ['spend','results','stat_cpa','stat_ctr','frequency','cpm']
        vals = [f"{k}: {_fmt_num(trends.get(k,0))}" for k in important if k in trends]
        if vals:
            lines.append('- اتجاهات مختصرة: ' + ' | '.join(vals))
        lines.append('')

    if diagnostics:
        lines.append('## التشخيص الأقرب')
        for d in diagnostics[:8]:
            lines.append(f"- **{d.get('scenario') or d.get('code') or d.get('family','تشخيص')}**: {d.get('diagnosis_ar') or d.get('explanation') or d.get('message','')}")
            decision = d.get('decision_ar') or d.get('recommended_action') or d.get('action')
            if decision:
                lines.append(f"  - القرار: {decision}")
            if d.get('next_metric'):
                lines.append(f"  - الرقم التالي للمراقبة: {d.get('next_metric')}")
        lines.append('')

    if human_insights:
        lines.append('## تفسير عملي بالعربي')
        for ins in human_insights[:5]:
            title = ins.get('title') or ins.get('type') or 'Insight'
            meaning = ins.get('meaning') or ins.get('explanation') or ''
            action = ins.get('action') or ins.get('decision') or ''
            lines.append(f'- **{title}:** {meaning}')
            if action:
                lines.append(f'  - الإجراء: {action}')
        lines.append('')

    if synthesis:
        lines.append('## التحليل المركب متعدد المتغيرات')
        for item in synthesis[:5]:
            lines.append(f"- **{item.get('title') or item.get('type','تركيب')}**: {item.get('meaning') or item.get('diagnosis') or item.get('explanation','')}")
            if item.get('action'):
                lines.append(f"  - الإجراء: {item.get('action')}")
        lines.append('')


    if deep_breakdowns:
        lines.append('## نتائج التحليل الأعمق حسب التقسيمات')
        for item in deep_breakdowns[:5]:
            plan = item.get('plan', {}) or {}
            summary = item.get('summary', {}) or {}
            if item.get('message'):
                lines.append(f"- **{plan.get('reason','deep breakdown')}**: لم يكتمل السحب العميق — {item.get('message')}")
                continue
            bds = ', '.join(summary.get('breakdowns', []) or plan.get('breakdowns', []) or [])
            lines.append(f"- **{plan.get('reason','deep breakdown')}** ({bds}) — صفوف: {summary.get('rows', 0)}")
            for seg in (summary.get('top_segments') or [])[:3]:
                seg_name = ' / '.join(str(seg.get(k,'')) for k in (summary.get('breakdowns') or []) if k in seg)
                lines.append(f"  - {seg_name}: spend={_fmt_num(seg.get('spend',0))}, results={_fmt_num(seg.get('results',0))}, clicks={_fmt_num(seg.get('clicks',0))}, ctr={_fmt_pct(seg.get('ctr',0))}")
        lines.append('')
    elif deep_plans:
        lines.append('## التحليل الأعمق المقترح')
        for plan in deep_plans[:5]:
            bds = ', '.join(plan.get('breakdowns', []) or [])
            lines.append(f"- {plan.get('reason','deep breakdown')}: اسحب breakdowns = {bds}")
        lines.append('')

    if skipped:
        lines.append('## أقسام لم يتم عرضها بسبب نقص البيانات')
        for s in skipped[:8]:
            req = ', '.join(s.get('required_fields', []) or [])
            lines.append(f"- {s.get('section')}: {s.get('reason')}" + (f" — مطلوب: {req}" if req else ''))
        lines.append('')

    lines.append('## الخطوة التالية')
    lines.append('راقب الرقم التالي المرتبط بالتشخيص، ثم شغّل التحليل الأعمق جدًا عند الحاجة إلى breakdowns أو تفسير زمني أكثر تفصيلًا.')
    return '\n'.join(lines)
