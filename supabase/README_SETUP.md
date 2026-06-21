# Supabase Setup

هذا الملف يجهز قاعدة البيانات من الصفر للمشروع.

## ماذا سيتم إنشاؤه؟

- جدول العملاء `tenant_accounts`
- إعدادات Meta لكل عميل `tenant_meta_apps`
- الداشبوردات العامة `dynamic_dashboards`
- مخازن البيانات المرنة `dashboard_datasets`
- سجلات JSON الخاصة بكل مخزن `dashboard_dataset_records`
- ربط Meta لكل عميل `meta_connections`
- ربط Google / GA4 لكل عميل `google_connections`
- أكواد OAuth المؤقتة `oauth_codes`
- توكنات التطبيق الداخلية `app_tokens`
- فهارس لتحسين السرعة
- حماية RLS حتى لا يستطيع أي عميل قراءة التوكنات مباشرة من المتصفح

## الخطوات

1. افتح مشروعك في Supabase.
2. من القائمة الجانبية افتح `SQL Editor`.
3. افتح الملف:
   `supabase/multi_tenant_schema.sql`
4. انسخ كل محتوى الملف.
5. الصقه في SQL Editor.
6. اضغط `Run`.

يمكن تشغيل نفس السكريبت أكثر من مرة بدون مشكلة.

## بعد تشغيل SQL

افتح `Project Settings` ثم `API` وخذ:

- `Project URL`
- `service_role key`

ثم ضعهم في بيئة تشغيل السيرفر:

```env
SUPABASE_URL=your_project_url
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
```

لا تضع `service_role key` في الواجهة الأمامية أو داخل Custom GPT.
هذا المفتاح للسيرفر فقط.

## اختبار سريع

بعد تشغيل السيرفر، افتح:

```text
/health/auth_connection_probe
```

لو Supabase متصل، لن تظهر رسالة:

```text
SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required.
```
