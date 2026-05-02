"""Unified local pipeline for Meta Ads intelligence.

Works with CSV/XLSX/JSON exports now, and can be fed by Meta API later.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Dict

import pandas as pd
import numpy as np

from app.analytics.analysis_storage import connect, prepare_raw_for_storage, save_run, upsert_df, save_relationship_edges, save_diagnostics
from app.analytics.semantic_metrics import expand_semantic_metrics
from app.analytics.intelligent_diagnostics import build_intelligence_diagnostics
from app.analytics.relationship_engine import discover_relationship_edges
from app.analytics.statistical_skills_layer import add_statistical_features, build_statistical_profile
from app.analytics.report_builder import build_dynamic_report_ar, build_skipped_sections
from app.analytics.baseline_engine import compute_internal_baselines
from app.analytics import supabase_storage
from app.analytics.meta_fetcher import recommend_breakdowns
from app.analytics.local_knowledge_feed import load_local_feed, feed_patterns, feed_principles


def load_export(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == '.csv':
        return pd.read_csv(path)
    if suffix in {'.xlsx', '.xls'}:
        return pd.read_excel(path)
    if suffix == '.json':
        data = json.loads(path.read_text(encoding='utf-8'))
        if isinstance(data, dict) and 'data' in data:
            data = data['data']
        return pd.DataFrame(data)
    raise ValueError(f'Unsupported file type: {suffix}')


def _metric_number_for_storage(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (list, tuple)):
        total = 0.0
        for item in value:
            if isinstance(item, dict):
                try:
                    total += float(item.get('value') or 0)
                except Exception:
                    pass
            else:
                try:
                    total += float(item or 0)
                except Exception:
                    pass
        return total
    if isinstance(value, dict):
        try:
            return float(value.get('value') or 0)
        except Exception:
            return 0.0
    try:
        if pd.isna(value):
            return 0.0
    except Exception:
        pass
    try:
        return float(value)
    except Exception:
        return 0.0


def _basic_metrics(df: pd.DataFrame) -> Dict[str, Any]:
    metrics: Dict[str, Any] = {'rows': int(len(df))}
    mean_cols = {'frequency', 'ctr_link', 'outbound_ctr', 'cpa', 'roas', 'signal_quality', 'cost_per_result', 'cost_per_message', 'click_to_message_rate', 'message_start_rate', 'result_rate_per_1000_reach', 'engagement_rate_calc'}
    for col in ['spend', 'impressions', 'reach', 'frequency', 'ctr_link', 'outbound_ctr', 'cpa', 'roas', 'signal_quality', 'results', 'link_clicks', 'messaging_conversations', 'cost_per_result', 'cost_per_message', 'click_to_message_rate', 'message_start_rate', 'result_rate_per_1000_reach', 'engagement_rate_calc']:
        if col in df.columns:
            series = pd.to_numeric(df[col], errors='coerce').fillna(0)
            metrics[col] = float(series.mean() if col in mean_cols else series.sum())
    return metrics



def infer_campaign_type_from_metrics(df: pd.DataFrame, fallback: str = 'unknown') -> str:
    requested = (fallback or 'unknown').lower()
    if requested != 'unknown':
        return requested
    if df is None or df.empty:
        return 'unknown'
    def total(col: str) -> float:
        if col not in df.columns:
            return 0.0
        return float(pd.to_numeric(df[col], errors='coerce').fillna(0).sum())
    if total('purchases') > 0 or total('purchase_value') > 0:
        return 'sales'
    if total('messaging_conversations') > 0:
        return 'messages'
    if total('leads') > 0:
        return 'leads'
    objective_text = ' '.join(str(x).lower() for x in df.get('objective', pd.Series(dtype=object)).dropna().unique().tolist())
    if 'message' in objective_text or 'engagement' in objective_text:
        return 'messages'
    if 'lead' in objective_text:
        return 'leads'
    if 'sales' in objective_text or 'conversion' in objective_text or 'purchase' in objective_text:
        return 'sales'
    if 'video' in objective_text:
        return 'video'
    if 'awareness' in objective_text or 'reach' in objective_text:
        return 'awareness'
    if 'traffic' in objective_text:
        return 'traffic'
    if 'app' in objective_text:
        return 'app'
    return 'unknown'

def _derived_for_storage(df: pd.DataFrame, level: str = 'campaign') -> pd.DataFrame:
    out = df.copy()
    if 'date' not in out.columns:
        if 'date_start' in out.columns:
            out['date'] = out['date_start']
        elif 'date_stop' in out.columns:
            out['date'] = out['date_stop']
        else:
            out['date'] = '1970-01-01'
    out['date'] = out['date'].replace('', '1970-01-01').fillna('1970-01-01')
    for col in ['account_id', 'campaign_id', 'adset_id', 'ad_id']:
        if col not in out.columns:
            out[col] = ''
    out['level'] = level
    out['breakdown_signature'] = ''
    if 'link_clicks' not in out.columns:
        if 'inline_link_clicks' in out.columns:
            out['link_clicks'] = out['inline_link_clicks']
        else:
            out['link_clicks'] = 0
    keep = [
        'date', 'account_id', 'campaign_id', 'adset_id', 'ad_id', 'level', 'breakdown_signature',
        'spend', 'impressions', 'reach', 'frequency', 'link_clicks', 'outbound_clicks',
        'landing_page_views', 'add_to_cart', 'initiate_checkout', 'purchases', 'leads',
        'messaging_conversations', 'purchase_value', 'ctr_link', 'outbound_ctr', 'lpv_rate',
        'atc_rate', 'checkout_rate', 'purchase_rate', 'cpa', 'cost_per_purchase', 'roas', 'signal_quality'
    ]
    id_cols = {'date', 'account_id', 'campaign_id', 'adset_id', 'ad_id', 'level', 'breakdown_signature'}
    for col in keep:
        if col not in out.columns:
            out[col] = 0 if col not in id_cols else ''
        elif col not in id_cols:
            out[col] = out[col].apply(_metric_number_for_storage)
    out['date'] = out['date'].apply(lambda v: v.date().isoformat() if hasattr(v, 'date') else str(v or '1970-01-01'))
    return out[keep]


def _feed_diagnostics(current: pd.DataFrame, campaign_type: str, level: str) -> list[dict[str, Any]]:
    """Apply deterministic patterns distilled from local research files."""
    if current is None or current.empty:
        return []
    def total(col: str) -> float:
        if col not in current.columns:
            return 0.0
        return float(pd.to_numeric(current[col], errors='coerce').fillna(0).sum())
    def mean(col: str) -> float:
        if col not in current.columns:
            return 0.0
        return float(pd.to_numeric(current[col], errors='coerce').replace([float('inf'), float('-inf')], 0).fillna(0).mean())
    spend = total('spend')
    results = total('results')
    impressions = total('impressions')
    link_clicks = total('link_clicks') or total('inline_link_clicks')
    outbound = total('outbound_clicks_count')
    lpv_rate = mean('lpv_rate')
    ctr = mean('link_ctr_calc') or (link_clicks / impressions if impressions else 0.0)
    cpm = mean('cpm')
    frequency = mean('frequency')
    diagnostics: list[dict[str, Any]] = []
    for pat in feed_patterns():
        key = pat.get('key')
        fire = False
        evidence = {'spend': spend, 'results': results, 'ctr': ctr, 'cpm': cpm, 'frequency': frequency, 'outbound_clicks': outbound, 'lpv_rate': lpv_rate}
        if key == 'message_campaign_not_website' and (campaign_type == 'messages' or total('messaging_conversations') > 0):
            fire = True
        elif key == 'click_lpv_gap' and outbound > 0 and lpv_rate < 0.45:
            fire = True
        elif key == 'clicks_without_signal' and link_clicks > 0 and results == 0:
            fire = True
        elif key == 'auction_pressure_cpm_ctr' and cpm > 0 and ctr > 0 and cpm >= mean('cpm') and ctr < 0.01:
            fire = True
        elif key == 'budget_scale_efficiency' and spend > 0 and results > 0:
            fire = True
        elif key == 'fatigue_frequency_ctr_cpa' and frequency >= 2 and ctr < 0.01:
            fire = True
        elif key == 'creative_attention_drop' and frequency >= 1.5 and ctr < 0.01:
            fire = True
        elif key == 'tracking_signal_gap' and link_clicks > 0 and total('purchase_value') == 0 and campaign_type in {'sales','unknown'}:
            fire = True
        if fire:
            diagnostics.append({
                'scenario': key,
                'family': pat.get('family') or 'local_feed',
                'severity': 'medium',
                'confidence': 'medium',
                'entity_level': level,
                'diagnosis_ar': pat.get('meaning_ar'),
                'decision_ar': pat.get('action_ar'),
                'recommended_action': pat.get('action_ar'),
                'next_metric': pat.get('next_metric'),
                'evidence': evidence,
                'source': 'local_research_feed',
            })
    return diagnostics


def _decision_for_relation(relation_type: str) -> tuple[str, str]:
    mapping = {
        'frequency_vs_ctr': ('إجهاد محتوى محتمل', 'راقب CTR والتكرار؛ جرّب زاوية/بداية جديدة قبل رفع الميزانية.'),
        'frequency_vs_outbound': ('تشبع أو ضعف نية بعد التكرار', 'اختبر جمهورًا أوسع أو رسالة مختلفة وراقب outbound CTR.'),
        'frequency_vs_cpa': ('التكرار يرفع تكلفة النتيجة', 'لا توسع الإنفاق قبل تقليل التشبع أو تجديد المحتوى.'),
        'auction_vs_ctr': ('ضغط مزاد مع تفاعل أضعف', 'راجع جودة الإعلان والجمهور والمواضع قبل زيادة الميزانية.'),
        'click_to_landing': ('تسريب بعد الضغط', 'افحص سرعة الصفحة/التتبع/ملاءمة الوجهة وراقب LPV rate.'),
        'click_intent_vs_signal': ('ضغطات بنية ضعيفة', 'راجع وعد الإعلان والجمهور وراقب signal quality.'),
        'spend_vs_results': ('العلاقة بين الإنفاق والنتائج', 'راقب هل زيادة الإنفاق تولّد نتائج بنفس الكفاءة أم تبدأ في الهدر.'),
        'spend_vs_cpa': ('زيادة الإنفاق مرتبطة بتكلفة أعلى', 'اختبر سقف توسع تدريجي وراقب CPA.'),
        'roas_vs_spend': ('تغير العائد مع الإنفاق', 'لا توسع قبل التأكد من ثبات ROAS أو قيمة النتيجة.'),
        'spend_vs_reach': ('الميزانية تفتح وصولًا إضافيًا', 'قيّم هل الوصول الإضافي يتحول إلى نتائج أو مجرد انتشار.'),
        'spend_vs_impressions': ('الميزانية تشتري ظهورًا', 'قارن الظهور بالضغطات والنتائج قبل زيادة الميزانية.'),
        'spend_vs_clicks': ('الميزانية تشتري ضغطات', 'اختبر جودة الضغطات وليس كميتها فقط.'),
        'clicks_vs_results': ('الضغطات مرتبطة بالنتائج', 'استخرج أفضل إعلانات/رسائل صنعت النية ووسعها بحذر.'),
        'inline_clicks_vs_results': ('ضغطات الرابط مرتبطة بالنتائج', 'ركز على زاوية الإعلان التي تولد ضغطات ذات نية.'),
        'outbound_clicks_vs_results': ('الخروج من الإعلان مرتبط بالنتائج', 'راجع الوجهة أو مسار الرسائل لتثبيت هذا المسار.'),
        'spend_clicks_results_triangle': ('مثلث الإنفاق والضغطات والنتائج', 'حلل هل الإنفاق يشتري نية حقيقية أم تفاعلًا سطحيًا.'),
        'frequency_vs_results': ('التكرار لا يضر النتائج حاليًا', 'راقبه عند التوسع لأن الإشارة قد تنقلب لتشبع.'),
        'impressions_vs_results': ('الظهور مرتبط بالنتائج', 'اختبر هل زيادة الظهور ما زالت تولد نتائج بنفس النسبة.'),
        'reach_vs_results': ('الوصول مرتبط بالنتائج', 'راقب جودة شرائح الجمهور وليس الحجم فقط.'),
    }
    return mapping.get(relation_type, ('علاقة رقمية مؤثرة', 'راقب المقياسين معًا ولا تحكم من رقم منفرد.'))


def _relationship_diagnostics(relationships: list[dict[str, Any]], level: str) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    for edge in relationships or []:
        title, action = _decision_for_relation(str(edge.get('relation_type') or ''))
        diagnostics.append({
            'scenario': edge.get('relation_type') or 'relationship_signal',
            'family': 'relationships_synthesis',
            'severity': 'high' if edge.get('confidence') == 'high' else 'medium',
            'confidence': edge.get('confidence') or 'medium',
            'entity_level': level,
            'diagnosis_ar': f"{title}: {edge.get('explanation_ar')}",
            'decision_ar': action,
            'recommended_action': action,
            'next_metric': edge.get('target_metric'),
            'evidence': edge.get('evidence', {}),
        })
    return diagnostics


def _relationship_synthesis(relationships: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for edge in (relationships or [])[:5]:
        title, action = _decision_for_relation(str(edge.get('relation_type') or ''))
        items.append({
            'type': edge.get('relation_type'),
            'level': edge.get('confidence') or 'medium',
            'title': title,
            'synthesis': edge.get('explanation_ar'),
            'root_cause': title,
            'action': action,
            'signals': {
                'source_metric': edge.get('source_metric'),
                'target_metric': edge.get('target_metric'),
                'weight': edge.get('weight'),
            },
        })
    return items


def _content_path_insights(current: pd.DataFrame, campaign_type: str) -> list[dict[str, Any]]:
    if current is None or current.empty:
        return []
    def total(col: str) -> float:
        if col not in current.columns:
            return 0.0
        return float(pd.to_numeric(current[col], errors='coerce').fillna(0).sum())
    def mean(col: str) -> float:
        if col not in current.columns:
            return 0.0
        return float(pd.to_numeric(current[col], errors='coerce').fillna(0).mean())
    insights: list[dict[str, Any]] = []
    link_clicks = total('link_clicks') or total('inline_link_clicks')
    outbound_clicks = total('outbound_clicks_count') or total('outbound_clicks')
    results = total('results')
    impressions = total('impressions')
    ctr = (link_clicks / impressions) if impressions else mean('ctr_link')
    frequency = mean('frequency')
    if campaign_type == 'messages' and results > 0:
        insights.append({
            'type': 'message_intent_path',
            'title': 'مسار الرسائل مستقل عن صفحة الهبوط',
            'synthesis': f'الحملة تبدو رسائل/تواصل؛ تم تقييم نية المحادثة من النتائج لا من شراء أو صفحة هبوط. النتائج المرصودة: {results:.0f}.',
            'action': 'حلل نص الإعلان والرسالة التي دفعت للتواصل، وراقب تكلفة بدء المحادثة وجودة الردود بدل فرض مسار شراء.',
            'signals': {'results': results, 'link_clicks': link_clicks, 'frequency': frequency, 'ctr_estimate': ctr},
        })
    if link_clicks > 0 and results == 0:
        insights.append({
            'type': 'curiosity_without_result',
            'title': 'ضغطات بلا نتيجة ظاهرة',
            'synthesis': 'يوجد تفاعل/ضغطات لكن لا توجد نتيجة مرصودة؛ هذا قد يعني فضول بلا نية أو فجوة بعد الضغط أو نقص تتبع.',
            'action': 'راجع وعد الإعلان والجمهور والتتبع، وراقب signal_quality أو تكلفة النتيجة.',
            'signals': {'link_clicks': link_clicks, 'outbound_clicks': outbound_clicks, 'results': results},
        })
    return insights



def _top_bottom_entities(df: pd.DataFrame, level: str, metric: str = 'budget_signal_score', limit: int = 3) -> dict[str, Any]:
    if df is None or df.empty or metric not in df.columns:
        return {'top': [], 'bottom': []}
    id_col = f'{level}_id'
    name_col = f'{level}_name'
    if id_col not in df.columns:
        id_col = 'ad_id' if 'ad_id' in df.columns else 'campaign_id' if 'campaign_id' in df.columns else ''
    if name_col not in df.columns:
        name_col = 'ad_name' if 'ad_name' in df.columns else 'campaign_name' if 'campaign_name' in df.columns else id_col
    if not id_col:
        return {'top': [], 'bottom': []}
    cols = [id_col, name_col, metric, 'spend', 'results', 'link_clicks', 'impressions', 'reach']
    cols = [c for c in cols if c in df.columns]
    tmp = df[cols].copy()
    tmp[metric] = pd.to_numeric(tmp[metric], errors='coerce').fillna(0)
    tmp = tmp.sort_values(metric, ascending=False)
    def rows(frame):
        out=[]
        for _, r in frame.iterrows():
            out.append({str(k): (float(v) if isinstance(v, (int, float, np.number)) else str(v)) for k,v in r.to_dict().items()})
        return out
    return {'top': rows(tmp.head(limit)), 'bottom': rows(tmp.tail(limit).sort_values(metric))}


def _portfolio_intelligence_insights(current: pd.DataFrame, campaign_type: str, level: str, relationships: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if current is None or current.empty:
        return []
    def total(col: str) -> float:
        if col not in current.columns:
            return 0.0
        return float(pd.to_numeric(current[col], errors='coerce').fillna(0).sum())
    def mean(col: str) -> float:
        if col not in current.columns:
            return 0.0
        return float(pd.to_numeric(current[col], errors='coerce').replace([np.inf, -np.inf], np.nan).fillna(0).mean())
    spend=total('spend'); results=total('results'); clicks=total('link_clicks'); impressions=total('impressions'); reach=total('reach')
    cpr = spend / results if results else 0
    ctr = clicks / impressions if impressions else mean('ctr_link')
    result_per_1000_reach = results / reach * 1000 if reach else 0
    top_bottom = _top_bottom_entities(current, level, 'budget_signal_score')
    out=[]
    out.append({
        'type':'executive_scorecard',
        'title':'بطاقة قرار تنفيذية للحملة',
        'synthesis': f'الحملة صرفت {spend:.2f} وحققت {results:.0f} نتيجة مع CTR تقديري {ctr:.4f} وتكلفة نتيجة {cpr:.2f}.',
        'action':'استخدم العلاقات لاختيار أين تزود الميزانية: زود فقط على الإعلانات التي تجمع بين ضغطات ونتائج وليس وصول فقط.',
        'signals': {'spend':spend,'results':results,'cost_per_result':cpr,'ctr':ctr,'result_per_1000_reach':result_per_1000_reach}
    })
    if top_bottom.get('top'):
        out.append({
            'type':'winner_loser_map',
            'title':'خريطة أفضل وأسوأ وحدات حسب كفاءة الميزانية',
            'synthesis':'تم ترتيب الوحدات حسب النتائج مقابل الإنفاق لتحديد أين يمكن التوسيع وأين يجب الإيقاف/إعادة الصياغة.',
            'action':'انقل ميزانية تدريجية من أضعف الوحدات إلى أفضلها، ثم اختبر مواضع/أجهزة قبل توسع كبير.',
            'signals': top_bottom
        })
    if campaign_type == 'messages':
        click_to_msg = mean('click_to_message_rate') or (results / clicks if clicks else 0)
        out.append({
            'type':'message_quality_layer',
            'title':'طبقة جودة الرسائل بعد الضغط',
            'synthesis': f'كمية الرسائل يجب تقييمها مع جودة المحادثة. معدل التحول من الضغط إلى نتيجة/رسالة تقديريًا {click_to_msg:.3f}.',
            'action':'اربط التحليل لاحقًا بجودة الردود/الكلمات المفتاحية داخل الرسائل، وليس بعدد الرسائل فقط.',
            'signals': {'click_to_message_rate':click_to_msg,'messages_or_results':results,'link_clicks':clicks}
        })
    strong = [r for r in relationships if abs(float(r.get('weight') or 0)) >= 0.65]
    if strong:
        out.append({
            'type':'relationship_cluster',
            'title':'عنقود العلاقات الأقوى',
            'synthesis': 'أقوى العلاقات تشير إلى المسار المسيطر في الحملة: ' + '، '.join([str(r.get('relation_type')) for r in strong[:5]]),
            'action':'لا تتخذ قرارًا من KPI منفرد؛ استخدم هذا العنقود لتحديد هل المشكلة في الميزانية أو الضغطات أو جودة النتيجة.',
            'signals': {'strong_relationships': strong[:5]}
        })
    return out


def analyze_dataframe(
    df: pd.DataFrame,
    compare_df: pd.DataFrame | None = None,
    campaign_type: str = 'unknown',
    question: str = '',
    level: str = 'campaign',
    db_path: str | Path | None = None,
) -> Dict[str, Any]:
    run_id = str(uuid.uuid4())
    current = expand_semantic_metrics(df)
    previous = expand_semantic_metrics(compare_df) if compare_df is not None else current.iloc[0:0].copy()

    campaign_type = infer_campaign_type_from_metrics(current, campaign_type)
    diagnostics_bundle = build_intelligence_diagnostics(current, previous, level=level, top_n=10)
    relationships = discover_relationship_edges(current)
    statistical_profile = build_statistical_profile(current, level=level)
    skipped = build_skipped_sections(current, campaign_type)
    metrics = _basic_metrics(current)
    diagnostics = diagnostics_bundle.get('top_diagnostics', []) or []
    local_feed_diagnostics = _feed_diagnostics(current, campaign_type, level)
    diagnostics = diagnostics + [d for d in local_feed_diagnostics if d.get('scenario') not in {x.get('scenario') for x in diagnostics}]
    if not diagnostics and relationships:
        diagnostics = _relationship_diagnostics(relationships, level)
    human_insights = diagnostics_bundle.get('human_insights', []) or []
    content_insights = _content_path_insights(current, campaign_type)
    portfolio_insights = _portfolio_intelligence_insights(current, campaign_type, level, relationships)
    multivariate_synthesis = diagnostics_bundle.get('multivariate_synthesis', []) or []
    if not multivariate_synthesis and relationships:
        multivariate_synthesis = _relationship_synthesis(relationships)
    multivariate_synthesis = content_insights + portfolio_insights + multivariate_synthesis
    deep_fetch_plans = [p.__dict__ for p in recommend_breakdowns(question, diagnostics)]

    result: Dict[str, Any] = {
        'run_id': run_id,
        'phase': 'basic+semantic+relationships+diagnostics+report',
        'summary_ar': diagnostics_bundle.get('summary_ar') or 'تم تحليل البيانات عبر طبقات المقاييس والعلاقات والتشخيص.',
        'rows': int(len(current)),
        'metrics': metrics,
        'statistical_profile': statistical_profile,
        'diagnostics': diagnostics,
        'human_insights': human_insights,
        'multivariate_synthesis': multivariate_synthesis,
        'relationships': relationships,
        'deep_fetch_plans': deep_fetch_plans,
        'skipped_sections': skipped + diagnostics_bundle.get('missing_notes', []),
        'objective_notes': diagnostics_bundle.get('objective_notes', []),
        'local_feed': {'version': load_local_feed().get('feed_version'), 'patterns_applied': len(local_feed_diagnostics), 'principles': feed_principles()},
        'storage_errors': [],
    }
    result['report_markdown'] = build_dynamic_report_ar(result, campaign_type=campaign_type, question=question)

    entity_col = f'{level}_id' if f'{level}_id' in current.columns else 'campaign_id'
    baselines = compute_internal_baselines(current, entity_col=entity_col, entity_level=level)
    raw_storage_df = prepare_raw_for_storage(df, level=level)
    derived_storage_df = _derived_for_storage(current, level=level)

    if db_path:
        con = None
        try:
            con = connect(db_path)
            upsert_df(con, 'raw_insights_daily', raw_storage_df)
            upsert_df(con, 'derived_metrics_daily', derived_storage_df)
            upsert_df(con, 'baselines', baselines)
            save_relationship_edges(con, run_id, relationships)
            save_diagnostics(con, run_id, result['diagnostics'], entity_level=level)
            save_run(
                con,
                run_id,
                scope='dataframe',
                level=level,
                period='',
                phase=result['phase'],
                completed_modules=['semantic_metrics', 'relationships', 'diagnostics', 'portfolio_intelligence', 'report'],
                skipped_modules=result['skipped_sections'],
                errors=[],
            )
        except Exception as exc:
            result['storage_errors'].append({'backend': 'sqlite', 'error_type': type(exc).__name__, 'message': str(exc)})
        finally:
            if con is not None:
                try:
                    con.close()
                except Exception:
                    pass

    if supabase_storage.enabled():
        try:
            supabase_storage.save_dataframe_outputs(
                run_id=run_id,
                raw_df=df,
                raw_storage_df=raw_storage_df,
                derived_df=derived_storage_df,
                baselines_df=baselines,
                relationships=relationships,
                diagnostics=result['diagnostics'],
                result=result,
                account_id=str(current.get('account_id', [''])[0]) if 'account_id' in current.columns and len(current) else '',
                campaign_id=str(current.get('campaign_id', [''])[0]) if 'campaign_id' in current.columns and len(current) else '',
                level=level,
                question=question,
                campaign_type=campaign_type,
            )
        except Exception as exc:
            result['storage_errors'].append({'backend': 'supabase', 'error_type': type(exc).__name__, 'message': str(exc)})
    return result


def analyze_file(
    path: str | Path,
    compare_path: str | Path | None = None,
    campaign_type: str = 'unknown',
    question: str = '',
    level: str = 'campaign',
    db_path: str | Path | None = None,
) -> Dict[str, Any]:
    df = load_export(path)
    compare_df = load_export(compare_path) if compare_path else None
    return analyze_dataframe(df, compare_df=compare_df, campaign_type=campaign_type, question=question, level=level, db_path=db_path)
