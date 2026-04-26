# Meta Ads Intelligence Layer

تمت إضافة طبقة تشخيص تعتمد على ملفات Downloads والبرومبت والخطة، وتعمل بدون أي API ذكاء صناعي خارجي.

## Endpoint
`POST /analysis/run`

```json
{
  "account_id": "act_xxx",
  "analysis_type": "intelligence_diagnostics",
  "level": "ad",
  "since": "2026-04-01",
  "until": "2026-04-07",
  "compare_since": "2026-03-25",
  "compare_until": "2026-03-31",
  "top_n": 10
}
```

## مصدر الذكاء
القواعد موجودة في:
`app/analytics/rules_catalog.json`

كل ما نضيف قاعدة جديدة تستخدم مقاييس موجودة، التطبيق يصبح أذكى بدون تغيير طبقة السحب.
لو القاعدة تحتاج metric جديد، نضيفه في `semantic_metrics.py`.
لو تحتاج field جديد من Meta، نضيفه في `DEFAULT_INSIGHTS_FIELDS` أو fields الطلب.

## الملفات المضافة
- `semantic_metrics.py`
- `statistics_engine.py`
- `rules_catalog.json`
- `diagnostic_rules_catalog.py`
- `arabic_explainer.py`
- `intelligent_diagnostics.py`
- `intelligence_storage.py`

## التخزين
كل تشغيل لـ `intelligence_diagnostics` يحفظ نسخة في:
`exports/meta_intelligence.sqlite`

## السيناريوهات الحالية
Creative Fatigue, Audience Saturation, Landing Page Friction, Offer/Product Friction, Checkout Friction, Budget Waste, Auction Pressure, Weak Signal Quality, Scale Candidate, Tracking/Attribution Mismatch, Weak Hook, Video Hold Problem, Message Match, Message Campaign Conversation Friction.
