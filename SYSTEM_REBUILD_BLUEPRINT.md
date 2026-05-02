# Manus Meta AI — System Rebuild Blueprint

## الهدف

تحويل التطبيق من مجموعة endpoints وتحليلات متفرقة إلى محلل بيانات إعلانات Meta مترابط، مفهوم، وسهل الاستخدام.

الهدف النهائي: المستخدم يسأل بلغة طبيعية مثل:

- حلل الحساب
- حلل آخر حملة
- حلل حملة كورسات
- قارن الأداء الأسبوع ده بالأسبوع اللي قبله
- أين الهدر؟
- ما الذي أوسعه وما الذي أوقفه؟

والسيرفر وحده يحدد النطاق، البيانات المطلوبة، التخزين، السحب الناقص، طبقة الإحصاء، العلاقات، التشخيص، والتقرير.

---

## المشكلة الحالية

التطبيق يحتوي على أجزاء قوية، لكنها ليست مربوطة بعقد موحد:

- Meta connection شغال.
- OAuth شغال.
- Supabase storage شغال.
- `/analysis/run` موجود.
- `statistical_skills_layer` موجود.
- `relationship_engine` موجود.
- `intelligent_diagnostics` موجود.
- `sync/meta` موجود.
- GPT schema اتعدل أكثر من مرة.

لكن المشكلة أن كل جزء أضيف كرد فعل على خطأ محدد، لذلك ظهرت تشوهات:

1. سؤال عن الحساب قد يتحول لتحليل حملة.
2. سؤال عن حملة قد يجلب بيانات خارج الحملة.
3. GPT كان يلف على `/insights` أو `/meta/request` بدل `/analysis/run`.
4. التخزين موجود لكن ليس هو مركز النظام.
5. السحب الدوري موجود كبداية، لكن ليس عنده سياسة واضحة.
6. لا يوجد contract واضح يقول: ما هو النطاق؟ ما الفترة؟ ما مصدر البيانات؟ ما الذي تم تحليله؟

---

## المبدأ الحاكم الجديد

لا يوجد تحليل خارج هذا المسار:

```text
User Question
→ Intent + Scope Resolver
→ Data Plan
→ Storage Coverage Check
→ Meta Delta Pull if needed
→ Normalization
→ Statistical Skills Layer
→ Relationship Discovery
→ Diagnostic Rule Mapping
→ Deep Breakdown Planner
→ Final Report
→ Storage Writeback
→ Audit Summary
```

أي endpoint أو أداة لا تخدم هذا المسار يجب أن تكون:

- مخفية عن GPT.
- أو داخلية فقط.
- أو محذوفة من schema.

---

## العقد الموحد للتحليل Analysis Contract

### Endpoint رئيسي واحد

```text
POST /analysis/run
```

هو المدخل الوحيد للتحليل.

### الطلب يجب أن يسمح بـ

```json
{
  "question": "حلل الحساب / حلل آخر حملة / حلل حملة كورسات",
  "account_id": "اختياري",
  "account_name": "اختياري",
  "campaign_id": "اختياري",
  "campaign_name": "اختياري",
  "analysis_type": "intelligence_diagnostics",
  "level": "campaign/adset/ad اختياري",
  "date_preset": "last_7d افتراضيًا",
  "since": "اختياري",
  "until": "اختياري"
}
```

### ممنوع على GPT

- `/insights`
- `/meta/request`
- raw Graph API analysis
- campaign{insights}

### مسموح لـ GPT

- `/analysis/run`
- `/accounts` فقط للمساعدة في الاختيار لو لزم
- تقارير/ملفات بعد التحليل

---

## Scope Resolver

أهم جزء في النظام.

وظيفته: يحدد المستخدم طلب ماذا بالضبط.

### حالات النطاق

#### 1. Account Scope

أمثلة:

- حلل الحساب
- حلل أداء الحساب
- أين الهدر في الحساب؟
- حلل كل الحملات

السلوك الصحيح:

```text
scope = account
level = campaign افتراضيًا
لا يتم اختيار حملة تلقائيًا
لا يتم وضع campaign filter
يتم تحليل الحملات داخل الحساب
```

#### 2. Campaign Scope

أمثلة:

- حلل آخر حملة
- حلل حملة كورسات
- حلل campaign id كذا

السلوك الصحيح:

```text
scope = campaign
resolve campaign_id
apply campaign filter إجباري
level = ad افتراضيًا للتحليل العميق
لا تدخل أي بيانات خارج الحملة
```

#### 3. Adset / Ad Scope

أمثلة:

- حلل الإعلانات
- حلل الأدستات
- أي إعلان أوقفه؟

السلوك الصحيح:

```text
scope = account أو campaign حسب السؤال
level = adset/ad
```

---

## Data Plan

قبل السحب يجب إنشاء خطة بيانات.

### مثال خطة لحساب

```json
{
  "scope": "account",
  "level": "campaign",
  "period": "last_7d",
  "breakdowns": [],
  "source_preference": "storage_first",
  "meta_pull_policy": "missing_delta_only"
}
```

### مثال خطة لحملة

```json
{
  "scope": "campaign",
  "campaign_id": "123",
  "level": "ad",
  "period": "last_7d",
  "breakdowns": [],
  "source_preference": "storage_first",
  "meta_pull_policy": "missing_delta_only"
}
```

### مثال خطة بسؤال عن الأجهزة

```json
{
  "scope": "campaign",
  "level": "ad",
  "breakdowns": ["impression_device"],
  "deep_pull_required": true
}
```

---

## Storage First Strategy

التخزين ليس أرشيفًا. التخزين هو ذاكرة المحلل.

### القاعدة

```text
لا تسحب من Meta إذا كانت البيانات المطلوبة موجودة وكافية في Supabase.
```

### خطوات التخزين

1. افحص `raw_insights_daily` حسب:
   - account_id
   - campaign_id إن وجد
   - level
   - date range
   - breakdown_signature

2. احسب coverage:
   - rows
   - days
   - missing_days
   - stale_until
   - campaign_strict_match

3. لو coverage كافية:
   - اقرأ من Supabase.

4. لو coverage ناقصة:
   - اسحب الناقص فقط من Meta.
   - خزنه.
   - ثم حلل من النسخة الموحدة.

---

## Meta Pull Policy

### ممنوع

- fetch_all عشوائي.
- كل الحسابات + كل الحملات + كل المستويات مرة واحدة.
- كل breakdowns مرة واحدة.
- time range كبير بدون سبب.

### مسموح

- bounded pull.
- last_7d default.
- yesterday/today للـ sync.
- max_pages محدود.
- fields whitelist.
- breakdown on demand.

---

## Scheduled Sync Strategy

بدل انتظار GPT يسحب كل مرة:

### كل يوم

```text
/sync/meta لكل حساب نشط
level = campaign
period = yesterday
```

### كل 6 ساعات

```text
active campaigns only
level = adset/ad حسب الأولوية
period = today أو last_3d
```

### عند طلب المستخدم

```text
storage first
pull missing only
```

### الهدف

- تقليل Meta limit.
- تسريع التحليل.
- بناء baseline تاريخي.
- تمكين اكتشاف الاتجاهات والشذوذ.

---

## Normalization Layer

تحويل raw Meta إلى أرقام مفهومة:

- actions → messages/leads/purchases/link_clicks
- action_values → purchase_value
- outbound clicks
- landing page views
- video p25/p50/p75/p95/p100
- cost_per_action_type

الخرج يجب أن يكون DataFrame موحد الأعمدة.

---

## Statistical Skills Layer

تعمل محليًا بعد السحب أو الكاش، ولا تؤثر على Meta limit.

يجب أن تنتج:

- derived ratios
- CTR/CPA/ROAS/LPV/signal quality
- baselines mean/median/std/p10/p90
- z-score anomalies
- trend slopes
- rankings
- decision scores SCALE/HOLD/KILL
- clustering
- forecast where sample allows
- sample sufficiency

---

## Relationship Discovery

لا تعمل على raw فقط. تعمل على normalized + statistical profile.

العلاقات المطلوبة:

- frequency vs CTR
- CPM vs CTR
- spend vs results
- clicks vs results
- outbound vs LPV
- spend + clicks + results triangle
- frequency + CPM + CTR triangle
- CTR + CPA + results

كل علاقة يجب أن تحتوي:

```json
{
  "metrics": [],
  "direction": "positive/negative/mixed",
  "strength": 0.0,
  "confidence": "low/medium/high",
  "evidence": {},
  "meaning_ar": "",
  "next_step": ""
}
```

---

## Diagnostic Layer

تحول الإحصاء والعلاقات إلى تشخيص.

أمثلة:

- Creative Fatigue
- Audience Saturation
- Auction Pressure
- Budget Waste
- Weak Signal Quality
- Landing Page Friction
- Message Campaign Friction
- Tracking Mismatch
- Scale Candidate
- Kill Candidate

كل تشخيص يجب أن يحتوي:

```json
{
  "scenario": "",
  "evidence": {},
  "confidence": "",
  "diagnosis_ar": "",
  "recommended_action": "",
  "next_metric": ""
}
```

---

## Deep Breakdown Planner

لا يسحب breakdowns إلا لو:

1. السؤال طلب ذلك.
2. التشخيص يحتاجه.
3. البيانات تكشف هدرًا لا يمكن تفسيره بدون تقسيم.

### triggers

- أجهزة → impression_device
- مواضع → publisher_platform + platform_position
- جمهور → age + gender
- دول → country
- وقت → hourly_stats

---

## Report Contract

التقرير النهائي يجب أن يبدأ بـ:

```text
الخلاصة: ...
```

ثم:

1. مصدر البيانات:
   - Supabase cache أو Meta live
   - rows/days/entities
   - هل تم السحب الناقص؟

2. ما العمليات التي تمت:
   - normalization
   - derived metrics
   - baselines
   - anomalies
   - trends
   - relationships
   - diagnostics

3. أهم العلاقات.

4. أهم التشخيصات.

5. قرارات:
   - SCALE
   - HOLD
   - KILL
   - TEST

6. خطة عمل:
   - الآن
   - خلال 72 ساعة
   - بعد أسبوع

7. بيانات ناقصة أو أقسام لم يتم تحليلها.

---

## Audit Output في كل تحليل

كل `/analysis/run` يجب أن يرجع metadata:

```json
{
  "scope": "account/campaign/adset/ad",
  "resolved_account_id": "",
  "resolved_campaign_id": "",
  "period": {},
  "source": "supabase_cache/meta_api/mixed",
  "cache_coverage": {},
  "meta_calls": [],
  "rows_used": 0,
  "strict_scope_filter_applied": true,
  "statistical_modules": [],
  "relationship_count": 0,
  "diagnostic_count": 0,
  "skipped_sections": [],
  "storage_write_status": {}
}
```

---

## Test Matrix الإجباري

لا يعتبر النظام صحيحًا إلا لو نجح في هذه الحالات:

### Scope tests

1. `حلل الحساب`
   - scope = account
   - لا يوجد campaign filter
   - level = campaign

2. `حلل آخر حملة`
   - scope = campaign
   - campaign_id resolved
   - campaign filter موجود
   - لا توجد بيانات خارج الحملة

3. `حلل حملة كورسات`
   - scope = campaign
   - name matching

4. `حلل الحساب حسب الحملات`
   - scope = account
   - level = campaign

5. `حلل الحساب حسب الإعلانات`
   - scope = account
   - level = ad
   - لا تختار حملة واحدة تلقائيًا

### Storage tests

6. بيانات موجودة في Supabase → source = supabase_cache
7. بيانات ناقصة → source = mixed أو meta_api + writeback
8. campaign_id filter → كل rows نفس campaign_id
9. account scope → rows من نفس account فقط

### Tool safety tests

10. GPT schema لا يحتوي `/insights`
11. GPT schema لا يحتوي `/meta/request`
12. account_id ليس required
13. campaign_id/campaign_name موجودان

### Analysis tests

14. statistical_profile موجود
15. relationships موجودة
16. diagnostics موجودة
17. report يذكر العمليات التي تمت
18. skipped_sections يذكر النواقص

---

## Backlog لإعادة البناء

### Phase 1 — Stabilize Contract

- تثبيت AnalysisRunRequest.
- تثبيت Scope Resolver.
- تثبيت DataPlan object.
- إرجاع audit metadata دائمًا.

### Phase 2 — Storage as Core

- بناء coverage engine.
- delta pull فقط.
- sync policies.
- storage read/write tests.

### Phase 3 — Analysis Quality

- ربط statistical_profile بالعلاقات فعليًا.
- تطوير relationship confidence.
- rule mapper واضح.
- report composer موحد.

### Phase 4 — GPT Schema Minimalism

- expose فقط:
  - `/analysis/run`
  - `/accounts`
  - report builders
- لا raw Graph API.

### Phase 5 — Automated Test Suite

- pytest لاختبارات scope/storage/schema.
- live smoke tests محدودة.
- regression suite قبل أي push.

---

## قرار معماري

من الآن:

```text
لا نصلح bug منفرد قبل تحديد أي طبقة كسرها.
```

أي مشكلة جديدة يتم تصنيفها:

- Scope Resolver
- Data Plan
- Storage Coverage
- Meta Pull
- Normalization
- Statistical Layer
- Relationship Layer
- Diagnostic Layer
- Report Layer
- GPT Schema Contract

ثم الإصلاح يتم داخل الطبقة المناسبة فقط.
