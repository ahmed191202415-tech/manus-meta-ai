from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["legal"])


def _page(title: str, body: str) -> HTMLResponse:
    html = f"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    body {{
      margin: 0;
      font-family: Tahoma, Arial, sans-serif;
      background: #f7f8fb;
      color: #17212b;
      line-height: 1.8;
    }}
    main {{
      max-width: 880px;
      margin: 0 auto;
      padding: 32px 18px 56px;
    }}
    section {{
      background: #fff;
      border: 1px solid #e5e9f0;
      border-radius: 8px;
      padding: 24px;
    }}
    h1 {{ margin-top: 0; }}
    h2 {{ margin: 24px 0 8px; }}
    p, li {{ color: #334155; }}
    a {{ color: #1455d9; }}
  </style>
</head>
<body>
<main>
  <section>{body}</section>
</main>
</body>
</html>"""
    return HTMLResponse(html)


@router.get("/privacy", response_class=HTMLResponse)
async def privacy_policy():
    return _page(
        "Privacy Policy",
        """
        <h1>سياسة الخصوصية</h1>
        <p>توضح هذه الصفحة كيف يتعامل تطبيق Manus Meta AI مع بيانات المستخدمين عند ربط حسابات Meta أو Google Analytics.</p>

        <h2>البيانات التي نجمعها</h2>
        <ul>
          <li>بيانات الربط التي يمنحها المستخدم عبر OAuth مثل access tokens و refresh tokens عند الحاجة.</li>
          <li>بيانات حسابات الإعلانات والتقارير والتحليلات التي يطلب المستخدم تحليلها.</li>
          <li>بيانات Google Analytics 4 التي يصرح المستخدم بقراءتها.</li>
        </ul>

        <h2>كيف نستخدم البيانات</h2>
        <p>نستخدم البيانات فقط لتقديم التحليلات، التقارير، وتشخيص أداء الحملات والموقع للعميل صاحب الحساب.</p>

        <h2>مشاركة البيانات</h2>
        <p>لا نبيع بيانات المستخدمين ولا نشاركها مع أطراف خارجية إلا عند الحاجة لتشغيل الخدمة أو الامتثال للقانون.</p>

        <h2>حماية البيانات</h2>
        <p>يتم تخزين بيانات الربط في قاعدة بيانات مخصصة للسيرفر، ولا يتم عرض التوكنات للمستخدمين أو للواجهة العامة.</p>

        <h2>حذف البيانات</h2>
        <p>يمكن للمستخدم طلب حذف بياناته أو فصل الربط من خلال التواصل مع مسؤول التطبيق أو استخدام صفحة حذف البيانات.</p>

        <h2>التواصل</h2>
        <p>لأي طلبات خصوصية أو حذف بيانات، تواصل مع مسؤول التطبيق.</p>
        """,
    )


@router.get("/terms", response_class=HTMLResponse)
async def terms_of_service():
    return _page(
        "Terms of Service",
        """
        <h1>شروط الاستخدام</h1>
        <p>باستخدام Manus Meta AI، يوافق المستخدم على استخدام الخدمة لأغراض تحليل التسويق والإعلانات والموقع فقط.</p>

        <h2>مسؤولية المستخدم</h2>
        <p>المستخدم مسؤول عن امتلاك الصلاحيات اللازمة للحسابات التي يربطها، وعن صحة بيانات التطبيقات التي يضيفها.</p>

        <h2>حدود الخدمة</h2>
        <p>التحليلات تعتمد على البيانات المتاحة من Meta و Google Analytics، وقد تتأثر جودة النتائج بنقص التتبع أو الصلاحيات.</p>

        <h2>إيقاف الربط</h2>
        <p>يمكن للمستخدم إلغاء ربط حساباته أو طلب حذف بياناته في أي وقت.</p>
        """,
    )


@router.get("/data-deletion", response_class=HTMLResponse)
async def data_deletion():
    return _page(
        "Data Deletion",
        """
        <h1>حذف بيانات المستخدم</h1>
        <p>إذا أردت حذف بياناتك من Manus Meta AI، يمكنك التواصل مع مسؤول التطبيق وطلب حذف الربط والبيانات المرتبطة بحسابك.</p>

        <h2>ما الذي يتم حذفه؟</h2>
        <ul>
          <li>توكنات ربط Meta و Google.</li>
          <li>إعدادات الربط المختارة مثل GA4 property أو صفحة Meta المختارة.</li>
          <li>أي سجلات تحليل محفوظة مرتبطة بالعميل عند توفرها.</li>
        </ul>

        <h2>خطوات الطلب</h2>
        <p>أرسل بريدك المستخدم في البوابة إلى مسؤول التطبيق مع طلب حذف البيانات. سيتم تنفيذ الطلب في أقرب وقت ممكن.</p>
        """,
    )
