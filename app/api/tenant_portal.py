from html import escape
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import ADMIN_API_KEY, ADMIN_EMAIL, ADMIN_PASSWORD, META_OAUTH_REDIRECT_URI, PUBLIC_BASE_URL
from app.core.connection_resolver import resolve_tenant_connection_state
from app.core.gpt_oauth_state import decode_gpt_oauth_state
from app.core.google_oauth import get_google_service_account_email
from app.core.oauth_store import (
    delete_access_email,
    ensure_allowed_tenant_by_email,
    get_active_google_connection_for_tenant,
    get_active_clarity_connection_for_tenant,
    get_tenant_status,
    list_dynamic_dashboards,
    list_tenant_accounts,
    normalize_email,
    set_access_email_status,
    update_tenant_meta_app,
    upsert_access_email,
)
from app.schemas.tenant_requests import (
    TenantAccessStatusRequest,
    TenantEmailAccessRequest,
    TenantMetaAppRequest,
)

router = APIRouter(prefix="/portal", tags=["portal"])


def _portal_url_for_email(email: str) -> str:
    clean_email = normalize_email(email)
    base_url = PUBLIC_BASE_URL or ""
    return f"{base_url}/portal/client?email={quote(clean_email)}" if base_url else f"/portal/client?email={quote(clean_email)}"


def _admin_access_items() -> list[dict]:
    items = list_tenant_accounts(include_deleted=True)
    enriched = []
    for item in items:
        status = get_tenant_status(item["tenant_id"])
        enriched.append({
            **item,
            "portal_url": _portal_url_for_email(item["email"]),
            "meta_app_configured": bool(status.get("meta_app", {}).get("configured")),
            "meta_connected": bool(status.get("meta_connection", {}).get("connected")),
            "meta_connection_mode": status.get("meta_connection", {}).get("connection_mode"),
            "meta_user_name": status.get("meta_connection", {}).get("meta_user_name"),
            "selected_page_name": status.get("meta_connection", {}).get("selected_page_name"),
            "google_connected": bool(get_active_google_connection_for_tenant(item["tenant_id"])),
            "clarity_connected": bool(get_active_clarity_connection_for_tenant(item["tenant_id"])),
        })
    return enriched


def _require_admin(request: Request):
    session_email = str(request.session.get("admin_email") or "").strip().lower()
    if ADMIN_EMAIL and ADMIN_PASSWORD and session_email == ADMIN_EMAIL:
        return
    provided = str(request.headers.get("x-admin-key") or "").strip()
    if ADMIN_API_KEY and provided == ADMIN_API_KEY:
        return
    if ADMIN_EMAIL and ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Admin login required.")
    if ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid admin key.")
    raise HTTPException(status_code=500, detail="Admin access is not configured.")


def _require_tenant(request: Request) -> str:
    tenant_id = str(request.session.get("tenant_id") or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Email verification required.")
    return tenant_id


def _page_shell(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{title}</title>
  <style>
    :root {{ --bg:#f4f7f9; --card:#ffffff; --text:#17232b; --muted:#667680; --accent:#126f78; --accent-dark:#0d5259; --line:#dce5e8; --ok:#217a50; --bad:#b63c48; --warn:#9a6a16; --soft:#f7fafb; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:Tahoma, Arial, sans-serif; background:var(--bg); color:var(--text); }}
    main {{ max-width:1180px; margin:0 auto; padding:26px 18px 60px; }}
    .card {{ background:var(--card); border:1px solid var(--line); border-radius:8px; padding:20px; margin-top:16px; box-shadow:0 8px 22px rgba(23,35,43,.05); }}
    .summary {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:12px; margin-top:16px; }}
    .mini {{ background:var(--card); border:1px solid var(--line); border-radius:8px; padding:15px; box-shadow:0 5px 14px rgba(23,35,43,.035); }}
    .mini strong {{ display:block; margin-bottom:6px; }}
    .step {{ display:inline-block; padding:5px 10px; border-radius:999px; background:#e7f1f2; color:var(--accent-dark); font-size:.84rem; margin-bottom:10px; }}
    .done {{ background:#e5f3ea; color:var(--ok); }}
    .blocked {{ background:#f7e2e2; color:var(--bad); }}
    h1, h2, h3 {{ margin:0 0 8px; }}
    p {{ line-height:1.7; margin:0; }}
    label {{ display:block; margin-top:12px; font-weight:700; }}
    input, button, select {{ width:100%; padding:12px; border-radius:6px; border:1px solid #cbd8dc; font:inherit; margin-top:8px; background:#fff; }}
    button {{ background:var(--accent); color:#fff; border:none; cursor:pointer; font-weight:700; transition:.18s ease; }}
    button:hover, a.button:hover {{ filter:brightness(.94); transform:translateY(-1px); }}
    button.secondary {{ background:#1d313d; }}
    button.warn {{ background:#8d2d2d; }}
    a.button {{ display:block; width:100%; text-align:center; text-decoration:none; padding:12px; border-radius:6px; background:#1d313d; color:#fff; font-weight:700; margin-top:10px; transition:.18s ease; }}
    pre {{ white-space:pre-wrap; word-break:break-word; background:#f4f8f9; padding:13px; border-radius:6px; border:1px solid var(--line); direction:ltr; text-align:left; }}
    .muted {{ color:var(--muted); font-size:.96rem; margin-top:6px; }}
    .hint {{ margin-top:10px; padding:10px 12px; border-radius:6px; background:#eef6f6; color:var(--accent-dark); }}
    .row {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:12px; }}
    table {{ width:100%; border-collapse:collapse; margin-top:12px; font-size:.95rem; }}
    th, td {{ border-bottom:1px solid #eadacc; padding:10px; text-align:right; vertical-align:top; }}
    .actions {{ display:flex; gap:8px; flex-wrap:wrap; }}
    .actions button {{ width:auto; min-width:90px; margin-top:0; }}
    .dashboard-grid {{ display:grid; grid-template-columns:1.2fr .8fr; gap:16px; margin-top:16px; }}
    .stat-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; }}
    .stat {{ background:#f8fbfc; border:1px solid var(--line); border-radius:8px; padding:16px; }}
    .stat b {{ display:block; font-size:1.2rem; margin-top:4px; }}
    .toolbar {{ display:flex; gap:10px; flex-wrap:wrap; margin-top:12px; }}
    .toolbar button, .toolbar a {{ width:auto; }}
    .pill {{ display:inline-block; padding:5px 10px; border-radius:999px; font-size:.85rem; }}
    .pill.ok {{ background:#e5f3ea; color:#256b45; }}
    .pill.bad {{ background:#f7e2e2; color:#8d2d2d; }}
    .pill.warn {{ background:#fff3dd; color:#8a5b00; }}
    .table-wrap {{ overflow:auto; }}
    .hero {{ display:flex; justify-content:space-between; align-items:center; gap:16px; flex-wrap:wrap; padding:18px 0 4px; }}
    .hero h1 {{ font-size:1.7rem; }}
    .hero-actions {{ display:flex; gap:8px; flex-wrap:wrap; }}
    .hero-actions a, .hero-actions button {{ width:auto; margin-top:0; }}
    .integration-grid {{ display:grid; gap:14px; }}
    .integration-head {{ display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap; }}
    .integration-head h2 {{ margin:0; }}
    .method-panel {{ display:none; margin-top:14px; padding:14px; border:1px solid var(--line); border-radius:6px; background:var(--soft); }}
    .method-panel.active {{ display:block; }}
    .status-line {{ display:flex; align-items:center; gap:8px; flex-wrap:wrap; }}
    .status-dot {{ width:9px; height:9px; border-radius:50%; background:#a8b3b7; display:inline-block; }}
    .status-dot.ok {{ background:var(--ok); }}
    .compact-actions {{ display:flex; gap:8px; flex-wrap:wrap; margin-top:12px; }}
    .compact-actions button, .compact-actions a {{ width:auto; min-width:130px; margin-top:0; }}
    .danger-link {{ background:var(--bad)!important; }}
    @media (max-width:760px) {{ .dashboard-grid {{ grid-template-columns:1fr; }} .compact-actions button, .compact-actions a {{ width:100%; }} }}
  </style>
</head>
<body>
<main>{body}</main>
</body>
</html>"""


def _admin_login_html(message: str = "") -> str:
    body = f"""
    <section class="card">
      <h1>دخول الأدمن</h1>
      <p>ادخل إيميل الأدمن والباسورد لفتح لوحة الإدارة.</p>
    </section>
    <section class="card">
      <label for="admin_email">Admin Email</label>
      <input id="admin_email" type="email" placeholder="admin@example.com" />
      <label for="admin_password">Admin Password</label>
      <input id="admin_password" type="password" placeholder="Password" />
      <p class="muted">{message}</p>
      <button onclick="adminLogin()">دخول</button>
    </section>
    <script>
      async function adminLogin() {{
        const response = await fetch("/portal/admin/session/login", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          credentials: "include",
          body: JSON.stringify({{
            email: document.getElementById("admin_email").value,
            password: document.getElementById("admin_password").value
          }})
        }});
        const text = await response.text();
        let data = null;
        try {{ data = text ? JSON.parse(text) : null; }} catch {{ data = {{ detail: text }}; }}
        if (!response.ok) {{
          alert((data && data.detail) ? JSON.stringify(data.detail) : text);
          return;
        }}
        window.location.href = "/portal/admin";
      }}
    </script>
    """
    return _page_shell("دخول الأدمن", body)


def _email_gate_html(message: str = "", email: str = "") -> str:
    body = f"""
    <section class="card">
      <h1>التحقق من البريد الإلكتروني</h1>
      <p>اكتب البريد الإلكتروني الذي أعطاك له الأدمن صلاحية استخدام النموذج. لو البريد غير مضاف أو موقوف، لن تقدر تكمل.</p>
    </section>
    <section class="card">
      <div class="step">الخطوة 1</div>
      <h2>أدخل البريد الإلكتروني</h2>
      <p class="muted">{message or 'سنستخدم البريد فقط لتحديد هل عندك صلاحية واختيار بياناتك المحفوظة.'}</p>
      <label for="email">البريد الإلكتروني</label>
      <input id="email" type="email" value="{email}" placeholder="name@example.com" />
      <button onclick="identifyEmail()">متابعة</button>
    </section>
    <script>
      async function identifyEmail() {{
        const email = document.getElementById("email").value;
        const response = await fetch("/portal/session/email", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          credentials: "include",
          body: JSON.stringify({{ email }})
        }});
        const text = await response.text();
        let data = null;
        try {{ data = text ? JSON.parse(text) : null; }} catch {{ data = {{ detail: text }}; }}
        if (!response.ok) {{
          alert((data && data.detail) ? JSON.stringify(data.detail) : text);
          return;
        }}
        window.location.href = "/portal";
      }}
    </script>
    """
    return _page_shell("بوابة البريد الإلكتروني", body)


def _portal_html(status: dict, redirect_uri: str, has_pending_gpt_oauth: bool = False, meta_oauth_error: dict | None = None) -> str:
    meta_app = status.get("meta_app") or {}
    connection = status.get("connection") or {}
    app_ready = bool(meta_app.get("configured"))
    connected = bool(connection.get("connected"))
    blocked = status.get("next_action") == "show_blocked"
    display_name = status.get("display_name") or "Client"
    email = status.get("email") or ""
    app_id_value = meta_app.get("meta_app_id") or ""
    message_for_user = status.get("message_for_user") or ""
    next_action = status.get("next_action") or "show_setup"

    setup_hint = ""
    reconnect_hint = ""
    if next_action == "show_setup":
        setup_hint = '<p class="hint">ابدأ من الخطوة 2 لأن بيانات التطبيق غير موجودة أو غير صحيحة.</p>'
    elif next_action == "show_reconnect":
        reconnect_hint = '<p class="hint">بيانات التطبيق محفوظة بالفعل. نفذ خطوة الربط فقط.</p>'
    elif next_action == "show_support":
        reconnect_hint = '<p class="hint">فيه مشكلة في الصلاحيات أو إعدادات التطبيق. راجع التشخيص ثم جرّب الربط.</p>'

    gpt_hint = ""
    gpt_continue_html = ""
    if has_pending_gpt_oauth:
        gpt_hint = '<section class="card"><div class="step">GPT</div><p>أنت جئت من داخل GPT. بعد إكمال الخطوات سيعود بك النظام إلى GPT تلقائيًا أو يمكنك الضغط على زر المتابعة.</p></section>'
        if connected and next_action == "continue":
            gpt_continue_html = '<a class="button" href="/oauth/continue">الرجوع إلى GPT الآن</a>'

    meta_error_html = ""
    if meta_oauth_error:
        reason = str(meta_oauth_error.get("reason") or "unknown")
        detail = str(meta_oauth_error.get("detail") or "")
        meta_error_html = f"""
        <section class="card">
          <div class="step blocked">Meta OAuth Error</div>
          <p>Reason: <strong>{reason}</strong></p>
          <pre>{detail}</pre>
        </section>
        """

    block_html = ""
    if blocked:
        block_html = """
        <section class="card">
          <div class="step blocked">الوصول موقوف</div>
          <p>هذا البريد الإلكتروني غير مفعل حاليًا. لن نستطيع المتابعة من هذه الصفحة حتى يتم تفعيله من الإدارة.</p>
        </section>
        """

    body = f"""
    <section class="card">
      <h1>ربط Meta مع النموذج</h1>
      <p>أهلًا {display_name}. البريد الحالي: <strong>{email}</strong>. هذه الصفحة لن تظهر لك إلا عند الحاجة فقط: أول إعداد، أو إعادة ربط، أو إصلاح مشكلة.</p>
    </section>
    {gpt_hint}
    {meta_error_html}

    <section class="summary">
      <div class="mini">
        <strong>حالة الوصول</strong>
        <span>{'مسموح' if not blocked else 'موقوف'}</span>
      </div>
      <div class="mini">
        <strong>حالة التطبيق</strong>
        <span>{'تم حفظ بيانات التطبيق' if app_ready else 'بيانات التطبيق غير مكتملة'}</span>
      </div>
      <div class="mini">
        <strong>حالة الربط</strong>
        <span>{'تم ربط Meta' if connected else 'Meta غير مربوطة الآن'}</span>
      </div>
    </section>

    <section class="card">
      <div class="step {'blocked' if blocked else ('done' if connected else '')}">التشخيص الحالي</div>
      <p>{message_for_user}</p>
    </section>

    {block_html}

    <section class="card">
      <div class="step {'done' if app_ready else ''}">الخطوة 1</div>
      <h2>تأكيد البريد الإلكتروني</h2>
      <p class="muted">تم حفظ البريد في الجلسة الحالية. لو أردت تغييره، استخدم الزر التالي.</p>
      <button class="secondary" onclick="switchEmail()">تغيير البريد الإلكتروني</button>
    </section>

    <section class="card">
      <div class="step {'done' if app_ready else ''}">الخطوة 2</div>
      <h2>أدخل بيانات تطبيق Meta</h2>
      <p class="muted">هذه الخطوة تظهر فقط عند أول إعداد أو لو احتجت تغيير بيانات التطبيق.</p>
      {setup_hint}
      <label for="meta_app_id">Meta App ID</label>
      <input id="meta_app_id" value="{app_id_value}" placeholder="Meta App ID" {'disabled' if blocked else ''} />
      <label for="meta_app_secret">Meta App Secret</label>
      <input id="meta_app_secret" type="password" placeholder="Meta App Secret" {'disabled' if blocked else ''} />
      <button onclick="saveMetaApp()" {'disabled' if blocked else ''}>حفظ بيانات التطبيق</button>
    </section>

    <section class="card">
      <div class="step {'done' if app_ready else ''}">الخطوة 3</div>
      <h2>ضع هذا الرابط داخل إعدادات Meta App</h2>
      <p class="muted">انسخ هذا الرابط وضعه في Valid OAuth Redirect URIs داخل تطبيق Meta.</p>
      <pre>{redirect_uri}</pre>
    </section>

    <section class="card">
      <div class="step {'done' if connected else ''}">الخطوة 4</div>
      <h2>اربط حساب Meta</h2>
      <p class="muted">لن تحتاج هذه الخطوة إلا عند أول ربط أو إذا انتهى الوصول أو تم سحبه.</p>
      {reconnect_hint}
      <a class="button" href="/auth/meta/login">Connect Meta</a>
      <label for="meta_manual_token">Or connect with a Meta Access Token</label>
      <input id="meta_manual_token" type="password" placeholder="Paste Meta Access Token" />
      <button onclick="connectMetaToken()">Connect using Access Token</button>
      <p class="muted">Only one Meta method stays active. Connecting with a token replaces the previous OAuth connection.</p>
      <a class="button" style="background:#8d2d2d" href="/auth/meta/disconnect">Remove saved Meta connection</a>
      {gpt_continue_html}
    </section>

    <script>
      async function saveMetaApp() {{
        try {{
          const response = await fetch("/portal/meta-app", {{
            method: "PUT",
            headers: {{ "Content-Type": "application/json" }},
            credentials: "include",
            body: JSON.stringify({{
              meta_app_id: document.getElementById("meta_app_id").value,
              meta_app_secret: document.getElementById("meta_app_secret").value,
              meta_oauth_scopes: "",
              webhook_verify_token: "",
              webhook_callback_url: ""
            }})
          }});
          const text = await response.text();
          let data = null;
          try {{ data = text ? JSON.parse(text) : null; }} catch {{ data = {{ detail: text }}; }}
          if (!response.ok) {{
            alert((data && data.detail) ? JSON.stringify(data.detail) : text);
            return;
          }}
          alert("تم حفظ بيانات التطبيق. اضغط Connect Meta عندما تكون جاهزًا للربط.");
          window.location.href = "/portal";
        }} catch (error) {{
          alert(error.message);
        }}
      }}

      async function switchEmail() {{
        await fetch("/portal/session/logout", {{ method: "POST", credentials: "include" }});
        window.location.href = "/portal";
      }}
    </script>
    """
    return _page_shell("ربط Meta", body)


def _admin_html() -> str:
    return _professional_admin_html()


def _professional_admin_html() -> str:
    body = """
    <header class="hero">
      <div>
        <h1>لوحة إدارة العملاء</h1>
        <p class="muted">أضف العملاء، راجع حالة الاشتراكات والربط، وافتح لوحة أي عميل لإدارة مصادر بياناته.</p>
      </div>
      <div class="hero-actions">
        <button class="secondary" onclick="loadAccess()">تحديث البيانات</button>
        <button class="warn" onclick="adminLogout()">تسجيل الخروج</button>
      </div>
    </header>
    <section class="dashboard-grid">
      <section class="card">
        <div class="step">إدارة عميل</div>
        <h2>إضافة أو تحديث عميل</h2>
        <div class="row">
          <div><label for="email">البريد الإلكتروني</label><input id="email" type="email" placeholder="client@example.com" /></div>
          <div><label for="display_name">اسم العميل</label><input id="display_name" placeholder="اسم العميل" /></div>
          <div><label for="subscription_days">مدة التفعيل بالأيام</label><input id="subscription_days" type="number" min="1" placeholder="30" /></div>
        </div>
        <button onclick="addAccess()">حفظ العميل</button>
        <p class="muted">بعد الحفظ افتح لوحة العميل لإضافة أو تعديل Meta وGoogle Analytics وClarity بالنيابة عنه.</p>
      </section>
      <section class="card">
        <div class="step">ملخص</div>
        <h2>حالة المنصة</h2>
        <div id="summary_wrap" class="stat-grid"></div>
      </section>
    </section>
    <section class="card">
      <div class="integration-head">
        <div><div class="step">العملاء</div><h2>قائمة العملاء</h2></div>
        <span class="muted">يمكن تعديل الاشتراك أو إيقاف العميل أو تنظيف بياناته بالكامل.</span>
      </div>
      <div id="table_wrap" class="table-wrap muted">جاري تحميل البيانات...</div>
    </section>
    <script>
      const statusBadge = (ok, yes = "متصل", no = "غير متصل") =>
        `<span class="pill ${ok ? "ok" : "bad"}">${ok ? yes : no}</span>`;
      async function api(url, options = {}) {
        const response = await fetch(url, { credentials:"include", ...options });
        const text = await response.text();
        let data = {};
        try { data = text ? JSON.parse(text) : {}; } catch { data = { detail:text }; }
        if (!response.ok) { alert(JSON.stringify(data.detail || data)); throw new Error("Request failed"); }
        return data;
      }
      async function loadAccess() {
        const data = await api("/portal/admin/access");
        const items = data.items || [];
        const active = items.filter(i => i.status === "active" && !i.subscription?.is_expired).length;
        document.getElementById("summary_wrap").innerHTML = `
          <div class="stat"><span>إجمالي العملاء</span><b>${items.length}</b></div>
          <div class="stat"><span>اشتراكات فعالة</span><b>${active}</b></div>
          <div class="stat"><span>Meta متصل</span><b>${items.filter(i => i.meta_connected).length}</b></div>
          <div class="stat"><span>Google متصل</span><b>${items.filter(i => i.google_connected).length}</b></div>`;
        const rows = items.map(item => `
          <tr>
            <td><strong>${item.display_name || "-"}</strong><div class="muted">${item.email || ""}</div></td>
            <td>${statusBadge(item.status === "active" && !item.subscription?.is_expired, item.status === "active" ? "فعال" : item.status, item.subscription?.is_expired ? "منتهي" : item.status)}</td>
            <td>${statusBadge(item.meta_connected)}<div class="muted">${item.meta_connection_mode || ""}</div></td>
            <td>${statusBadge(item.google_connected)}</td>
            <td>${statusBadge(item.clarity_connected)}</td>
            <td>${item.subscription?.access_expires_at || "غير محدد"}</td>
            <td>
              <div class="actions">
                <a class="button" href="${item.portal_url}" target="_blank">إدارة الربط</a>
                <button onclick="renewAccess('${item.email}')">تجديد</button>
                <button class="secondary" onclick="setStatus('${item.email}','disabled')">إيقاف</button>
                <button class="warn" onclick="deleteAccess('${item.email}')">حذف</button>
              </div>
            </td>
          </tr>`).join("");
        document.getElementById("table_wrap").innerHTML = `<table><thead><tr><th>العميل</th><th>الاشتراك</th><th>Meta</th><th>Google</th><th>Clarity</th><th>ينتهي في</th><th>إجراءات</th></tr></thead><tbody>${rows}</tbody></table>`;
      }
      async function addAccess() {
        await api("/portal/admin/access", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({
          email:document.getElementById("email").value, display_name:document.getElementById("display_name").value,
          subscription_days:document.getElementById("subscription_days").value ? parseInt(document.getElementById("subscription_days").value,10) : null
        })}); loadAccess();
      }
      async function renewAccess(email) {
        const days = parseInt(prompt("عدد أيام التجديد", "30"),10); if (!days) return;
        await api("/portal/admin/access/status", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({email,status:"active",subscription_days:days}) }); loadAccess();
      }
      async function setStatus(email,status) { await api("/portal/admin/access/status", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({email,status})}); loadAccess(); }
      async function deleteAccess(email) { if(confirm("سيتم حذف العميل وكل بيانات الربط المحفوظة. هل أنت متأكد؟")) { await api("/portal/admin/access?email="+encodeURIComponent(email),{method:"DELETE"}); loadAccess(); } }
      async function adminLogout() { await api("/portal/admin/session/logout",{method:"POST"}); window.location.href="/portal/admin"; }
      loadAccess();
    </script>
    """
    return _page_shell("إدارة العملاء", body)


def _legacy_admin_html() -> str:
    body = """
    <section class="card">
      <h1>لوحة إدارة العملاء</h1>
      <p>من هنا تضيف العملاء، تراجع حالة الاشتراك، وتشوف هل ربطوا Meta أم لا.</p>
      <div class="toolbar">
        <button class="secondary" onclick="loadAccess()">تحديث البيانات</button>
        <button class="secondary" onclick="adminLogout()">تسجيل خروج</button>
      </div>
    </section>
    <section class="dashboard-grid">
      <section class="card">
        <h2>إضافة أو تحديث عميل</h2>
        <label for="email">Email</label>
        <input id="email" type="email" placeholder="client@example.com" />
        <label for="display_name">Display Name</label>
        <input id="display_name" placeholder="Client Name" />
        <label for="subscription_days">مدة التفعيل بالأيام</label>
        <input id="subscription_days" type="number" min="1" placeholder="مثال: 30" />
        <p class="muted">رابط العميل هو الرابط الذي ترسله له ليفتح صفحته مباشرة ويبدأ الإعداد أو إعادة الربط.</p>
        <button onclick="addAccess()">حفظ العميل</button>
      </section>
      <section class="card">
        <h2>ملخص سريع</h2>
        <div id="summary_wrap" class="stat-grid">
          <div class="stat"><span>إجمالي العملاء</span><b>0</b></div>
          <div class="stat"><span>اشتراكات سارية</span><b>0</b></div>
          <div class="stat"><span>منتهية</span><b>0</b></div>
          <div class="stat"><span>Meta مربوطة</span><b>0</b></div>
        </div>
      </section>
    </section>
    <section class="card">
      <h2>العملاء</h2>
      <div id="table_wrap" class="table-wrap muted">اضغط تحديث البيانات.</div>
    </section>
    <script>
      function adminHeaders() {
        return {
          "Content-Type": "application/json"
        };
      }

      async function loadAccess() {
        const response = await fetch("/portal/admin/access", { headers: adminHeaders(), credentials: "include" });
        const text = await response.text();
        let data = null;
        try { data = text ? JSON.parse(text) : null; } catch { data = { detail: text }; }
        if (!response.ok) {
          alert((data && data.detail) ? JSON.stringify(data.detail) : text);
          return;
        }
        const items = data.items || [];
        const activeCount = items.filter(item => item.status === "active" && !item.subscription?.is_expired).length;
        const expiredCount = items.filter(item => item.subscription?.is_expired).length;
        const connectedCount = items.filter(item => item.meta_connected).length;
        document.getElementById("summary_wrap").innerHTML = `
          <div class="stat"><span>إجمالي العملاء</span><b>${items.length}</b></div>
          <div class="stat"><span>اشتراكات سارية</span><b>${activeCount}</b></div>
          <div class="stat"><span>منتهية</span><b>${expiredCount}</b></div>
          <div class="stat"><span>Meta مربوطة</span><b>${connectedCount}</b></div>
        `;
        const rows = items.map(item => `
          <tr>
            <td>${item.email || ""}</td>
            <td>${item.display_name || ""}</td>
            <td><span class="pill ${item.status === "active" ? "ok" : (item.status === "disabled" ? "warn" : "bad")}">${item.status || ""}</span></td>
            <td>${item.subscription?.access_expires_at || "غير محدد"}</td>
            <td><span class="pill ${item.subscription?.is_expired ? "bad" : "ok"}">${item.subscription?.is_expired ? "منتهي" : "ساري"}</span></td>
            <td>${item.meta_app_configured ? "تم" : "لا"}</td>
            <td>${item.meta_connected ? "تم" : "لا"}</td>
            <td>${item.meta_user_name || ""}</td>
            <td>${item.selected_page_name || ""}</td>
            <td>${item.added_at || ""}</td>
            <td>${item.updated_at || ""}</td>
            <td>
              <div><a href="${item.portal_url || "#"}" target="_blank">فتح صفحة العميل</a></div>
              <div class="muted">${item.portal_url || ""}</div>
              <div class="actions">
                <button onclick="renewAccess('${item.email}')">تجديد/تفعيل</button>
                <button class="secondary" onclick="setStatus('${item.email}', 'disabled')">إيقاف</button>
                <button class="warn" onclick="deleteAccess('${item.email}')">تنظيف كامل</button>
              </div>
            </td>
          </tr>
        `).join("");
        document.getElementById("table_wrap").innerHTML = `
          <table>
            <thead>
              <tr>
                <th>الإيميل</th>
                <th>الاسم</th>
                <th>الحالة</th>
                <th>ينتهي في</th>
                <th>حالة الاشتراك</th>
                <th>بيانات Meta App</th>
                <th>ربط Meta</th>
                <th>اسم حساب Meta</th>
                <th>الصفحة المختارة</th>
                <th>تاريخ الإضافة</th>
                <th>آخر تعديل</th>
                <th>إجراءات</th>
              </tr>
            </thead>
            <tbody>${rows}</tbody>
          </table>
        `;
      }

      async function addAccess() {
        const response = await fetch("/portal/admin/access", {
          method: "POST",
          headers: adminHeaders(),
          credentials: "include",
          body: JSON.stringify({
            email: document.getElementById("email").value,
            display_name: document.getElementById("display_name").value,
            subscription_days: document.getElementById("subscription_days").value ? parseInt(document.getElementById("subscription_days").value, 10) : null
          })
        });
        const text = await response.text();
        let data = null;
        try { data = text ? JSON.parse(text) : null; } catch { data = { detail: text }; }
        if (!response.ok) {
          alert((data && data.detail) ? JSON.stringify(data.detail) : text);
          return;
        }
        loadAccess();
      }

      async function renewAccess(email) {
        const daysValue = prompt("اكتب عدد أيام التفعيل الجديدة لهذا العميل", document.getElementById("subscription_days").value || "30");
        if (!daysValue) return;
        const subscription_days = parseInt(daysValue, 10);
        if (!subscription_days || subscription_days < 1) {
          alert("اكتب عدد أيام صحيح.");
          return;
        }
        const response = await fetch("/portal/admin/access/status", {
          method: "POST",
          headers: adminHeaders(),
          credentials: "include",
          body: JSON.stringify({ email, status: "active", subscription_days })
        });
        const text = await response.text();
        let data = null;
        try { data = text ? JSON.parse(text) : null; } catch { data = { detail: text }; }
        if (!response.ok) {
          alert((data && data.detail) ? JSON.stringify(data.detail) : text);
          return;
        }
        loadAccess();
      }

      async function setStatus(email, status) {
        const response = await fetch("/portal/admin/access/status", {
          method: "POST",
          headers: adminHeaders(),
          credentials: "include",
          body: JSON.stringify({ email, status })
        });
        const text = await response.text();
        let data = null;
        try { data = text ? JSON.parse(text) : null; } catch { data = { detail: text }; }
        if (!response.ok) {
          alert((data && data.detail) ? JSON.stringify(data.detail) : text);
          return;
        }
        loadAccess();
      }

      async function deleteAccess(email) {
        if (!confirm("سيتم حذف المستخدم وتنظيف كل بياناته المحفوظة: Meta وGoogle وClarity وGPT tokens. هل أنت متأكد؟")) return;
        const response = await fetch("/portal/admin/access?email=" + encodeURIComponent(email), {
          method: "DELETE",
          credentials: "include"
        });
        const text = await response.text();
        let data = null;
        try { data = text ? JSON.parse(text) : null; } catch { data = { detail: text }; }
        if (!response.ok) {
          alert((data && data.detail) ? JSON.stringify(data.detail) : text);
          return;
        }
        loadAccess();
      }

      async function adminLogout() {
        await fetch("/portal/admin/session/logout", { method: "POST", credentials: "include" });
        window.location.href = "/portal/admin";
      }
    </script>
    """
    return _page_shell("إدارة الوصول", body)


def _client_dashboard_html(
    tenant_id: str,
    user_email: str,
    meta_status: dict,
    google_connection: dict | None,
    clarity_connection: dict | None,
    service_account_email: str,
    schema_url: str,
    has_pending_gpt_oauth: bool,
    dashboards: list[dict] | None = None,
) -> str:
    meta_connection = meta_status.get("meta_connection") or {}
    meta_app = meta_status.get("meta_app") or {}
    meta_connected = bool(meta_connection.get("connected"))
    google_connected = bool(google_connection)
    clarity_connected = bool(clarity_connection)
    property_id = escape(str((google_connection or {}).get("selected_ga4_property_id") or ""))
    property_name = escape(str((google_connection or {}).get("selected_ga4_property_name") or ""))
    clarity_name = escape(str((clarity_connection or {}).get("project_name") or ""))
    dashboard_rows = ""
    for item in dashboards or []:
        dashboard_id = escape(str(item.get("dashboard_id") or ""))
        dashboard_title = escape(str(item.get("title") or "Untitled dashboard"))
        dashboard_description = escape(str(item.get("description") or ""))
        dashboard_status = escape(str(item.get("status") or "active"))
        dashboard_updated = escape(str(item.get("last_refreshed_at") or item.get("updated_at") or ""))
        dashboard_rows += f"""
        <tr>
          <td><strong>{dashboard_title}</strong><div class="muted">{dashboard_description}</div></td>
          <td>{dashboard_status}</td>
          <td>{dashboard_updated}</td>
          <td><a class="button" href="/dynamic_dashboards/{dashboard_id}" target="_blank">Open</a></td>
        </tr>
        """
    if not dashboard_rows:
        dashboard_rows = '<tr><td colspan="4" class="muted">No dashboards yet. Ask GPT to create one.</td></tr>'
    gpt_continue = '<a class="button" href="/oauth/continue">الرجوع إلى GPT ومتابعة التحليل</a>' if has_pending_gpt_oauth and meta_connected else ""
    body = f"""
    <header class="hero">
      <div>
        <h1>مركز ربط مصادر البيانات</h1>
        <p class="muted">أدر ربط Meta وGoogle Analytics وMicrosoft Clarity من مكان واحد.</p>
        <p class="muted">{escape(user_email)}</p>
      </div>
      <div class="hero-actions">
        {gpt_continue}
        <button class="secondary" onclick="logout()">تغيير البريد</button>
      </div>
    </header>
    <section class="summary">
      <div class="mini"><strong>Meta Ads</strong><div class="status-line"><i class="status-dot {'ok' if meta_connected else ''}"></i><span>{'متصل' if meta_connected else 'غير متصل'}</span></div><div class="muted">{escape(str(meta_connection.get('connection_mode') or ''))}</div></div>
      <div class="mini"><strong>Google Analytics</strong><div class="status-line"><i class="status-dot {'ok' if google_connected else ''}"></i><span>{'متصل' if google_connected else 'غير متصل'}</span></div><div class="muted">{escape(str((google_connection or {}).get('connection_mode') or ''))}</div></div>
      <div class="mini"><strong>Microsoft Clarity</strong><div class="status-line"><i class="status-dot {'ok' if clarity_connected else ''}"></i><span>{'متصل' if clarity_connected else 'غير متصل'}</span></div><div class="muted">{clarity_name}</div></div>
      <div class="mini"><strong>GA4 Property</strong><div class="status-line"><i class="status-dot {'ok' if property_id else ''}"></i><span>{property_name or property_id or 'لم يتم الاختيار'}</span></div></div>
    </section>

    <section class="card">
      <div class="integration-head"><div><div class="step">Meta Ads</div><h2>ربط حساب Meta</h2></div><span class="pill {'ok' if meta_connected else 'bad'}">{'متصل' if meta_connected else 'غير متصل'}</span></div>
      <label for="meta_method">طريقة الربط</label>
      <select id="meta_method" onchange="toggleMethods()">
        <option value="">اختر طريقة الربط</option>
        <option value="oauth">تطبيق Meta مخصص + تسجيل دخول Facebook</option>
        <option value="token">Access Token يدوي</option>
      </select>
      <div id="meta_oauth_panel" class="method-panel">
        <h3>تطبيق Meta مخصص</h3>
        <p class="muted">احفظ App ID وApp Secret، ثم اضغط تسجيل الدخول. أي ربط سابق سيتم استبداله بعد نجاح الربط الجديد.</p>
        <label for="meta_app_id">App ID</label><input id="meta_app_id" value="{escape(str(meta_app.get('meta_app_id') or ''))}" placeholder="Meta App ID" />
        <label for="meta_app_secret">App Secret</label><input id="meta_app_secret" type="password" placeholder="Meta App Secret" />
        <div class="compact-actions"><button onclick="saveMetaApp()">حفظ بيانات التطبيق</button><a class="button" href="/auth/meta/login">تسجيل الدخول عبر Facebook</a></div>
      </div>
      <div id="meta_token_panel" class="method-panel">
        <h3>Access Token يدوي</h3>
        <p class="muted">استخدم هذه الطريقة بمفردها. عند الحفظ سيتم حذف ربط OAuth السابق لمنع التعارض.</p>
        <label for="meta_manual_token">Access Token</label><input id="meta_manual_token" type="password" placeholder="Paste Meta Access Token" />
        <button onclick="connectMetaToken()">ربط باستخدام التوكن</button>
      </div>
      <div class="compact-actions"><button class="warn" onclick="disconnectMeta()">حذف ربط Meta</button></div>
    </section>

    <section class="card">
      <div class="integration-head"><div><div class="step">Google Analytics</div><h2>ربط GA4</h2></div><span class="pill {'ok' if google_connected else 'bad'}">{'متصل' if google_connected else 'غير متصل'}</span></div>
      <label for="google_method">طريقة الربط</label>
      <select id="google_method" onchange="toggleMethods()">
        <option value="">اختر طريقة الربط</option>
        <option value="oauth">تسجيل الدخول بحساب Google</option>
        <option value="service">منح صلاحية لإيميل الخدمة</option>
      </select>
      <div id="google_oauth_panel" class="method-panel">
        <h3>تسجيل الدخول بحساب Google</h3>
        <p class="muted">الطريقة المناسبة لمعظم المستخدمين، وتدعم التجديد التلقائي للصلاحية.</p>
        <a class="button" href="/auth/google/login?tenant_id={quote(tenant_id)}">تسجيل الدخول عبر Google</a>
      </div>
      <div id="google_service_panel" class="method-panel">
        <h3>منح صلاحية داخل GA4</h3>
        <p class="muted">أضف الإيميل التالي كـ Viewer داخل GA4 Property، ثم اكتب Property ID.</p>
        <pre>{escape(service_account_email or 'Service Account غير مضاف على السيرفر حتى الآن.')}</pre>
        <label for="service_property_id">Property ID</label><input id="service_property_id" value="{property_id}" placeholder="529884683" />
        <label for="service_property_name">اسم الموقع</label><input id="service_property_name" value="{property_name}" placeholder="Website name" />
        <button onclick="connectGoogleService()">ربط بالصلاحية</button>
      </div>
      <div class="method-panel active">
        <h3>Property المختارة</h3>
        <div class="row"><div><label for="property_id">Property ID</label><input id="property_id" value="{property_id}" placeholder="529884683" /></div><div><label for="property_name">اسم الموقع</label><input id="property_name" value="{property_name}" placeholder="Website name" /></div></div>
        <button onclick="selectProperty()">تحديث Property</button>
      </div>
      <div class="compact-actions"><a class="button" href="/ga4/properties?tenant_id={quote(tenant_id)}">عرض Properties المتاحة</a><button class="warn" onclick="disconnectGoogle()">حذف ربط Google</button></div>
    </section>

    <section class="card">
      <div class="integration-head"><div><div class="step">Microsoft Clarity</div><h2>ربط سلوك الزوار</h2></div><span class="pill {'ok' if clarity_connected else 'bad'}">{'متصل' if clarity_connected else 'غير متصل'}</span></div>
      <label for="clarity_project_name">اسم المشروع</label><input id="clarity_project_name" value="{clarity_name}" placeholder="Project name" />
      <label for="clarity_token">API Token</label><input id="clarity_token" type="password" placeholder="Paste Clarity API Token" />
      <div class="compact-actions"><button onclick="saveClarity()">حفظ وربط Clarity</button><button class="warn" onclick="disconnectClarity()">حذف ربط Clarity</button></div>
    </section>

    <section class="card">
      <div class="integration-head"><div><div class="step">Dynamic Dashboards</div><h2>Dashboards created by GPT</h2></div><span class="pill ok">{len(dashboards or [])}</span></div>
      <p class="muted">Each customer dashboard can have a different design, filters, widgets, and data sources. The links stay here.</p>
      <table>
        <thead><tr><th>Name</th><th>Status</th><th>Last refresh</th><th>Link</th></tr></thead>
        <tbody>{dashboard_rows}</tbody>
      </table>
    </section>

    <section class="card">
      <div class="step">GPT Actions</div><h2>رابط Schema</h2>
      <pre>{escape(schema_url)}</pre><button onclick="copySchema()">نسخ الرابط</button>
    </section>
    <script>
      async function api(url, options={{}}) {{
        const response=await fetch(url,{{credentials:"include",...options}}); const text=await response.text(); let data={{}};
        try{{data=text?JSON.parse(text):{{}}}}catch{{data={{detail:text}}}} if(!response.ok){{alert(JSON.stringify(data.detail||data));throw new Error("Request failed")}} return data;
      }}
      function toggleMethods() {{
        const meta=document.getElementById("meta_method").value, google=document.getElementById("google_method").value;
        document.getElementById("meta_oauth_panel").classList.toggle("active",meta==="oauth"); document.getElementById("meta_token_panel").classList.toggle("active",meta==="token");
        document.getElementById("google_oauth_panel").classList.toggle("active",google==="oauth"); document.getElementById("google_service_panel").classList.toggle("active",google==="service");
      }}
      async function saveMetaApp() {{ await api("/portal/meta-app",{{method:"PUT",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{meta_app_id:document.getElementById("meta_app_id").value,meta_app_secret:document.getElementById("meta_app_secret").value}})}}); alert("تم حفظ بيانات التطبيق"); location.reload(); }}
      async function connectMetaToken() {{ await api("/auth/meta/connect_token",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{access_token:document.getElementById("meta_manual_token").value}})}}); location.reload(); }}
      async function disconnectMeta() {{ if(confirm("حذف ربط Meta؟")){{await api("/auth/meta/disconnect",{{method:"POST"}});location.reload();}} }}
      async function connectGoogleService() {{ await api("/auth/google/connect_service_account",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{property_id:document.getElementById("service_property_id").value,property_name:document.getElementById("service_property_name").value}})}});location.reload(); }}
      async function disconnectGoogle() {{ if(confirm("حذف ربط Google؟")){{await api("/auth/google/disconnect",{{method:"POST"}});location.reload();}} }}
      async function selectProperty() {{ await api("/ga4/select_property",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{tenant_id:"{escape(tenant_id)}",property_id:document.getElementById("property_id").value,property_name:document.getElementById("property_name").value}})}});location.reload(); }}
      async function saveClarity() {{ await api("/clarity/connect_token",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{tenant_id:"{escape(tenant_id)}",api_token:document.getElementById("clarity_token").value,project_name:document.getElementById("clarity_project_name").value}})}});location.reload(); }}
      async function disconnectClarity() {{ if(confirm("حذف ربط Clarity؟")){{await api("/clarity/disconnect",{{method:"POST"}});location.reload();}} }}
      async function copySchema() {{ await navigator.clipboard.writeText("{escape(schema_url)}"); alert("تم نسخ الرابط"); }}
      async function logout() {{ await api("/portal/session/logout",{{method:"POST"}});location.href="/portal"; }}
    </script>
    """
    return _page_shell("مركز ربط مصادر البيانات", body)


@router.get("", response_class=HTMLResponse)
async def portal_home(request: Request, email: str | None = None, gpt_oauth: str | None = None):
    gpt_state = decode_gpt_oauth_state(gpt_oauth)
    if gpt_state:
        request.session["gpt_oauth_redirect_uri"] = gpt_state.get("redirect_uri")
        request.session["gpt_oauth_state"] = gpt_state.get("state") or ""
        request.session["gpt_oauth_client_id"] = gpt_state.get("client_id")

    if email and not request.session.get("tenant_id"):
        try:
            record = ensure_allowed_tenant_by_email(email)
            request.session["tenant_id"] = record["tenant_id"]
            request.session["user_email"] = record["email"]
        except ValueError:
            pass

    tenant_id = str(request.session.get("tenant_id") or "").strip()
    if not tenant_id:
        return HTMLResponse(_email_gate_html(email=email or ""))

    return RedirectResponse(url="/portal/client", status_code=302)


@router.get("/client", response_class=HTMLResponse)
async def client_dashboard(request: Request, email: str | None = None):
    if email:
        try:
            record = ensure_allowed_tenant_by_email(email)
            request.session["tenant_id"] = record["tenant_id"]
            request.session["user_email"] = record["email"]
        except ValueError:
            return HTMLResponse(_email_gate_html(email=email or ""))

    tenant_id = str(request.session.get("tenant_id") or "").strip()
    if not tenant_id:
        return HTMLResponse(_email_gate_html(email=email or ""))

    meta_status = get_tenant_status(tenant_id)
    google_connection = get_active_google_connection_for_tenant(tenant_id)
    clarity_connection = get_active_clarity_connection_for_tenant(tenant_id)
    dashboards = list_dynamic_dashboards(tenant_id, limit=100)
    service_account_email = get_google_service_account_email()
    meta_app_id = (meta_status.get("meta_app") or {}).get("meta_app_id") or ""
    meta_connection_mode = (meta_status.get("meta_connection") or {}).get("connection_mode") or ""
    google_connection_mode = (google_connection or {}).get("connection_mode") or ""
    selected_property_id = (google_connection or {}).get("selected_ga4_property_id") or ""
    selected_property_name = (google_connection or {}).get("selected_ga4_property_name") or ""
    user_email = request.session.get("user_email") or tenant_id
    schema_url = f"{PUBLIC_BASE_URL}/openapi-gpt.json" if PUBLIC_BASE_URL else "/openapi-gpt.json"
    return HTMLResponse(_client_dashboard_html(
        tenant_id=tenant_id,
        user_email=user_email,
        meta_status=meta_status,
        google_connection=google_connection,
        clarity_connection=clarity_connection,
        service_account_email=service_account_email,
        schema_url=schema_url,
        has_pending_gpt_oauth=bool(request.session.get("gpt_oauth_redirect_uri")),
        dashboards=dashboards,
    ))
    body = f"""
    <section class="card">
      <h1>لوحة ربط العميل</h1>
      <p>من هنا العميل يربط Meta و Google Analytics، يختار GA4 Property، وينسخ رابط GPT Schema.</p>
      <p class="muted">Tenant ID: <strong>{tenant_id}</strong></p>
    </section>
    <section class="summary">
      <div class="mini"><strong>Meta</strong><span>{'متصل - ' + meta_connection_mode if meta_status.get('meta_connection', {}).get('connected') else 'غير متصل'}</span></div>
      <div class="mini"><strong>Google</strong><span>{'متصل - ' + google_connection_mode if google_connection else 'غير متصل'}</span></div>
      <div class="mini"><strong>Clarity</strong><span>{'متصل' if clarity_connection else 'غير متصل'}</span></div>
      <div class="mini"><strong>GA4 Property</strong><span>{selected_property_name or selected_property_id or 'لم يتم الاختيار'}</span></div>
    </section>
    <section class="card">
      <h2>1. ربط Meta</h2>
      <p class="muted">اختر طريقة واحدة فقط. عند استخدام طريقة جديدة يتم حذف الربط السابق تلقائيًا.</p>
      <h3>الطريقة الأولى: تطبيق Meta مخصص + مصادقة Facebook</h3>
      <label for="meta_app_id">Meta App ID</label>
      <input id="meta_app_id" placeholder="Meta App ID" value="{meta_app_id}" />
      <label for="meta_app_secret">Meta App Secret</label>
      <input id="meta_app_secret" type="password" placeholder="Meta App Secret" />
      <button onclick="saveMetaApp()">Save Meta App</button>
      <a class="button" href="/auth/meta/login">Connect Meta with Facebook Login</a>
      <h3>الطريقة الثانية: Access Token</h3>
      <label for="meta_manual_token">Meta Access Token</label>
      <input id="meta_manual_token" type="password" placeholder="Paste Meta Access Token" />
      <button onclick="connectMetaToken()">Connect Meta using Access Token</button>
      <button class="warn" onclick="disconnectMeta()">Disconnect Meta</button>
    </section>
    <section class="card">
      <h2>2. ربط Google Analytics</h2>
      <p class="muted">اختر المصادقة أو منح الصلاحية لإيميل الخدمة. عند تغيير الطريقة يتم استبدال الربط السابق.</p>
      <h3>الطريقة الأولى: Google Login</h3>
      <a class="button" href="/auth/google/login?tenant_id={tenant_id}">Connect Google with Login</a>
      <h3>الطريقة الثانية: منح صلاحية داخل GA4</h3>
      <p class="muted">أضف الإيميل التالي بصلاحية Viewer داخل GA4 Property ثم اكتب Property ID واضغط Connect.</p>
      <pre>{service_account_email or 'Service Account is not configured on the server yet.'}</pre>
      <label for="service_property_id">Property ID</label>
      <input id="service_property_id" placeholder="529884683" value="{selected_property_id}" />
      <label for="service_property_name">Property Name</label>
      <input id="service_property_name" placeholder="Website name" value="{selected_property_name}" />
      <button onclick="connectGoogleServiceAccount()">Connect by granted permission</button>
      <button class="warn" onclick="disconnectGoogle()">Disconnect Google</button>
      <p class="muted">بعد الربط افتح خصائص GA4 من الرابط التالي.</p>
      <a class="button" href="/ga4/properties?tenant_id={tenant_id}">Show GA4 Properties</a>
    </section>
    <section class="card">
      <h2>3. اختيار GA4 Property</h2>
      <p class="muted">لو عندك Property ID اكتبه هنا مرة واحدة.</p>
      <label for="property_id">Property ID</label>
      <input id="property_id" placeholder="529884683" value="{selected_property_id}" />
      <label for="property_name">Property Name</label>
      <input id="property_name" placeholder="Website name" value="{selected_property_name}" />
      <button onclick="selectProperty()">Save GA4 Property</button>
    </section>
    <section class="card">
      <h2>4. ربط Microsoft Clarity</h2>
      <p class="muted">هات API Token من Clarity Settings ثم Data Export.</p>
      <label for="clarity_project_name">Project Name</label>
      <input id="clarity_project_name" placeholder="Project name" value="{(clarity_connection or {}).get('project_name') or ''}" />
      <label for="clarity_token">Clarity API Token</label>
      <input id="clarity_token" type="password" placeholder="Paste Clarity API token" />
      <button onclick="saveClarity()">Save Clarity Token</button>
      <button class="warn" onclick="disconnectClarity()">Disconnect Clarity</button>
    </section>
    <section class="card">
      <h2>5. إعداد GPT</h2>
      <p>ضع هذا الرابط في GPT Actions:</p>
      <pre>{schema_url}</pre>
      <button onclick="copySchema()">Copy Schema URL</button>
    </section>
    <script>
      async function apiRequest(url, options = {{}}) {{
        const response = await fetch(url, {{ credentials: "include", ...options }});
        const text = await response.text();
        let data = null;
        try {{ data = text ? JSON.parse(text) : null; }} catch {{ data = {{ detail: text }}; }}
        if (!response.ok) {{
          alert((data && data.detail) ? JSON.stringify(data.detail) : text);
          throw new Error("Request failed");
        }}
        return data;
      }}
      async function saveMetaApp() {{
        await apiRequest("/portal/meta-app", {{
          method: "PUT",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{
            meta_app_id: document.getElementById("meta_app_id").value,
            meta_app_secret: document.getElementById("meta_app_secret").value
          }})
        }});
        alert("Meta App saved. Press Facebook Login when ready.");
        window.location.reload();
      }}
      async function connectMetaToken() {{
        await apiRequest("/auth/meta/connect_token", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ access_token: document.getElementById("meta_manual_token").value }})
        }});
        alert("Meta connected using Access Token. Previous Meta connection was replaced.");
        window.location.reload();
      }}
      async function disconnectMeta() {{
        await apiRequest("/auth/meta/disconnect", {{ method: "POST" }});
        window.location.reload();
      }}
      async function connectGoogleServiceAccount() {{
        await apiRequest("/auth/google/connect_service_account", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{
            property_id: document.getElementById("service_property_id").value,
            property_name: document.getElementById("service_property_name").value
          }})
        }});
        alert("Google Analytics connected by granted permission.");
        window.location.reload();
      }}
      async function disconnectGoogle() {{
        await apiRequest("/auth/google/disconnect", {{ method: "POST" }});
        window.location.reload();
      }}
      async function selectProperty() {{
        const property_id = document.getElementById("property_id").value;
        const property_name = document.getElementById("property_name").value;
        const response = await fetch("/ga4/select_property", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          credentials: "include",
          body: JSON.stringify({{ tenant_id: "{tenant_id}", property_id, property_name }})
        }});
        if (!response.ok) {{
          alert(await response.text());
          return;
        }}
        alert("تم حفظ GA4 Property");
        window.location.reload();
      }}

      async function connectMetaToken() {{
        const response = await fetch("/auth/meta/connect_token", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          credentials: "include",
          body: JSON.stringify({{ access_token: document.getElementById("meta_manual_token").value }})
        }});
        const text = await response.text();
        let data = null;
        try {{ data = text ? JSON.parse(text) : null; }} catch {{ data = {{ detail: text }}; }}
        if (!response.ok) {{
          alert((data && data.detail) ? JSON.stringify(data.detail) : text);
          return;
        }}
        alert("Meta connected using the Access Token. Any previous Meta connection was replaced.");
        window.location.href = "/portal";
      }}
      async function saveClarity() {{
        const api_token = document.getElementById("clarity_token").value;
        const project_name = document.getElementById("clarity_project_name").value;
        const response = await fetch("/clarity/connect_token", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          credentials: "include",
          body: JSON.stringify({{ tenant_id: "{tenant_id}", api_token, project_name }})
        }});
        if (!response.ok) {{
          alert(await response.text());
          return;
        }}
        alert("تم حفظ Clarity Token");
        window.location.reload();
      }}
      async function disconnectClarity() {{
        await apiRequest("/clarity/disconnect", {{ method: "POST" }});
        window.location.reload();
      }}
      async function copySchema() {{
        await navigator.clipboard.writeText("{schema_url}");
        alert("تم نسخ رابط Schema");
      }}
    </script>
    """
    return HTMLResponse(_page_shell(f"Client Dashboard - {user_email}", body))


@router.post("/session/email")
async def session_email(body: TenantEmailAccessRequest, request: Request):
    try:
        record = ensure_allowed_tenant_by_email(body.email, display_name=body.display_name)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    request.session["tenant_id"] = record["tenant_id"]
    request.session["user_email"] = record["email"]
    return resolve_tenant_connection_state(record["tenant_id"])


@router.post("/session/logout")
async def session_logout(request: Request):
    request.session.pop("tenant_id", None)
    request.session.pop("user_email", None)
    request.session.pop("meta_access_token", None)
    request.session.pop("meta_user_id", None)
    request.session.pop("meta_user", None)
    return {"success": True}


@router.put("/meta-app")
async def put_portal_meta_app(body: TenantMetaAppRequest, request: Request):
    tenant_id = _require_tenant(request)
    status = resolve_tenant_connection_state(tenant_id)
    if status.get("next_action") == "show_blocked":
        raise HTTPException(status_code=403, detail="This email is currently disabled.")

    meta_app = update_tenant_meta_app(
        tenant_id=tenant_id,
        meta_app_id=body.meta_app_id,
        meta_app_secret=body.meta_app_secret,
        meta_oauth_scopes="",
        webhook_verify_token="",
        webhook_callback_url="",
    )
    return {
        "success": True,
        "tenant_id": tenant_id,
        "meta_app_id": meta_app.get("meta_app_id"),
        "configured": bool(meta_app.get("meta_app_id") and meta_app.get("meta_app_secret")),
    }


@router.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    session_email = str(request.session.get("admin_email") or "").strip().lower()
    if ADMIN_EMAIL and ADMIN_PASSWORD and session_email != ADMIN_EMAIL:
        return HTMLResponse(_admin_login_html())
    return HTMLResponse(_admin_html())


@router.post("/admin/session/login")
async def admin_login(request: Request):
    if not ADMIN_EMAIL or not ADMIN_PASSWORD:
        raise HTTPException(status_code=500, detail="Admin email/password are not configured.")
    body = await request.json()
    email = normalize_email((body or {}).get("email"))
    password = str((body or {}).get("password") or "")
    if email != ADMIN_EMAIL or password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="بيانات دخول الأدمن غير صحيحة.")
    request.session["admin_email"] = email
    return {"success": True, "admin_email": email}


@router.post("/admin/session/logout")
async def admin_logout(request: Request):
    request.session.pop("admin_email", None)
    return {"success": True}


@router.get("/admin/access")
async def admin_list_access(request: Request):
    _require_admin(request)
    return {"items": _admin_access_items()}


@router.post("/admin/access")
async def admin_add_access(body: TenantEmailAccessRequest, request: Request):
    _require_admin(request)
    try:
        item = upsert_access_email(
            body.email,
            display_name=body.display_name,
            status="active",
            subscription_days=body.subscription_days,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"item": item}


@router.post("/admin/access/status")
async def admin_set_access_status(body: TenantAccessStatusRequest, request: Request):
    _require_admin(request)
    try:
        item = set_access_email_status(body.email, body.status, subscription_days=body.subscription_days)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"item": item}


@router.delete("/admin/access")
async def admin_delete_access(request: Request, email: str = Query(...)):
    _require_admin(request)
    try:
        item = delete_access_email(email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"item": item}


@router.post("/admin/access/purge")
async def admin_purge_access(body: TenantEmailAccessRequest, request: Request):
    _require_admin(request)
    try:
        item = delete_access_email(body.email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "success": True,
        "message": "Tenant and all saved integrations were cleaned.",
        "item": item,
    }


@router.get("/admin/access/invite-url")
async def admin_access_url(request: Request, email: str = Query(...)):
    _require_admin(request)
    clean_email = normalize_email(email)
    url = _portal_url_for_email(clean_email)
    return {"email": clean_email, "portal_url": url}
