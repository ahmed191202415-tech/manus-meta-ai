from html import escape
from json import dumps
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.config import PUBLIC_BASE_URL
from app.core.auth import resolve_access_token
from app.core.oauth_store import (
    create_dynamic_dashboard,
    delete_dynamic_dashboard,
    get_app_token_data,
    get_dynamic_dashboard,
    list_dynamic_dashboards,
    update_dynamic_dashboard_config,
    update_dynamic_dashboard_snapshot,
)
from app.schemas.dynamic_dashboard_requests import (
    DynamicDashboardCreateRequest,
    DynamicDashboardRefreshRequest,
    DynamicDashboardSnapshotRequest,
    DynamicDashboardUpdateRequest,
)

router = APIRouter(prefix="/dynamic_dashboards", tags=["dynamic dashboards"])


def _tenant_from_request(request: Request, supplied_tenant_id: str | None = None) -> str:
    tenant_id = str(supplied_tenant_id or request.session.get("tenant_id") or "").strip()
    if tenant_id:
        return tenant_id
    authorization = str(request.headers.get("authorization") or "")
    if authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        app_data = get_app_token_data(token) if token.startswith("app_") else None
        tenant_id = str((app_data or {}).get("tenant_id") or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Tenant is required.")
    return tenant_id


def _dashboard_link(dashboard_id: str) -> str:
    base = PUBLIC_BASE_URL or ""
    return f"{base}/dynamic_dashboards/{dashboard_id}" if base else f"/dynamic_dashboards/{dashboard_id}"


def _config_from_body(body: DynamicDashboardCreateRequest | DynamicDashboardUpdateRequest) -> dict:
    config: dict = {}
    if getattr(body, "filters", None) is not None:
        config["filters"] = [item.model_dump() for item in (body.filters or [])]
    if getattr(body, "data_sources", None) is not None:
        config["data_sources"] = [item.model_dump() for item in (body.data_sources or [])]
    if getattr(body, "widgets", None) is not None:
        config["widgets"] = [item.model_dump() for item in (body.widgets or [])]
    if getattr(body, "layout", None) is not None:
        config["layout"] = body.layout or {}
    return config


def _visible_dashboard(row: dict) -> dict:
    refresh_status = _refresh_status(row)
    return {
        "dashboard_id": row.get("dashboard_id"),
        "tenant_id": row.get("tenant_id"),
        "title": row.get("title"),
        "description": row.get("description"),
        "status": row.get("status"),
        "config": row.get("config") or {},
        "refresh_policy": row.get("refresh_policy") or {},
        "last_refreshed_at": row.get("last_refreshed_at"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "url": _dashboard_link(str(row.get("dashboard_id") or "")),
        "refresh_status": refresh_status,
    }


def _parse_dt(value) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _refresh_interval(policy: dict) -> timedelta | None:
    mode = str((policy or {}).get("mode") or (policy or {}).get("type") or "on_open").strip().lower()
    if mode == "hourly":
        return timedelta(hours=1)
    if mode == "daily":
        return timedelta(days=1)
    minutes = (policy or {}).get("interval_minutes")
    if minutes:
        return timedelta(minutes=max(1, int(minutes)))
    return None


def _refresh_status(row: dict) -> dict:
    policy = row.get("refresh_policy") or {}
    mode = str(policy.get("mode") or policy.get("type") or "on_open").strip().lower()
    last_refreshed = _parse_dt(row.get("last_refreshed_at"))
    now = datetime.now(timezone.utc)
    interval = _refresh_interval(policy)
    stale = False
    reason = "fresh"
    next_refresh_at = None
    if mode == "manual":
        stale = False
        reason = "manual_refresh_only"
    elif not last_refreshed:
        stale = True
        reason = "never_refreshed"
    elif mode == "on_open":
        stale = bool(policy.get("refresh_on_open", True))
        reason = "refresh_on_open" if stale else "fresh"
    elif interval:
        due_at = last_refreshed + interval
        next_refresh_at = due_at.isoformat()
        stale = due_at <= now
        reason = "scheduled_refresh_due" if stale else "fresh"
    return {
        "mode": mode,
        "stale": stale,
        "reason": reason,
        "last_refreshed_at": row.get("last_refreshed_at"),
        "next_refresh_at": next_refresh_at,
    }


def _refresh_steps(row: dict) -> list[dict]:
    steps = []
    config = row.get("config") or {}
    for source in config.get("data_sources") or []:
        source_type = source.get("source") or "manual"
        name = source.get("name") or source_type
        query = source.get("query") or {}
        if source_type == "meta":
            steps.append({"source": name, "tool": "/meta/smart_insights", "body": query})
        elif source_type == "ga4":
            steps.append({"source": name, "tool": "/tools/ga4", "body": query})
        elif source_type == "clarity":
            steps.append({"source": name, "tool": "/tools/clarity", "body": query})
        elif source_type == "journey":
            steps.append({"source": name, "tool": "/tools/journey", "body": query})
        else:
            steps.append({"source": name, "tool": "manual_snapshot", "body": query})
    return steps


@router.post("/create")
async def create_dashboard(body: DynamicDashboardCreateRequest, request: Request, token: str = Depends(resolve_access_token)):
    tenant_id = _tenant_from_request(request, body.tenant_id)
    row = create_dynamic_dashboard(
        tenant_id=tenant_id,
        title=body.title,
        description=body.description,
        config=_config_from_body(body),
        snapshot=body.initial_snapshot,
        refresh_policy=body.refresh_policy,
    )
    return {"success": True, "dashboard": _visible_dashboard(row), "url": _dashboard_link(row["dashboard_id"])}


@router.get("/list")
async def list_dashboards(request: Request, tenant_id: str | None = None, limit: int = 100):
    resolved_tenant_id = _tenant_from_request(request, tenant_id)
    return {
        "tenant_id": resolved_tenant_id,
        "dashboards": [_visible_dashboard(item) for item in list_dynamic_dashboards(resolved_tenant_id, limit=limit)],
    }


@router.patch("/{dashboard_id}")
async def update_dashboard(dashboard_id: str, body: DynamicDashboardUpdateRequest, request: Request):
    tenant_id = _tenant_from_request(request, body.tenant_id)
    payload = {}
    if body.title is not None:
        payload["title"] = body.title
    if body.description is not None:
        payload["description"] = body.description
    if body.status is not None:
        payload["status"] = body.status
    config = _config_from_body(body)
    if config:
        existing = get_dynamic_dashboard(dashboard_id) or {}
        merged_config = {**(existing.get("config") or {}), **config}
        payload["config"] = merged_config
    if body.refresh_policy is not None:
        payload["refresh_policy"] = body.refresh_policy
    row = update_dynamic_dashboard_config(tenant_id, dashboard_id, payload)
    if not row:
        raise HTTPException(status_code=404, detail="Dashboard was not found.")
    return {"success": True, "dashboard": _visible_dashboard(row)}


@router.post("/{dashboard_id}/snapshot")
async def update_dashboard_snapshot(dashboard_id: str, body: DynamicDashboardSnapshotRequest, request: Request):
    tenant_id = _tenant_from_request(request, body.tenant_id)
    row = update_dynamic_dashboard_snapshot(tenant_id, dashboard_id, body.snapshot)
    if not row:
        raise HTTPException(status_code=404, detail="Dashboard was not found.")
    return {"success": True, "dashboard": _visible_dashboard(row)}


@router.post("/{dashboard_id}/refresh")
async def refresh_dashboard(dashboard_id: str, body: DynamicDashboardRefreshRequest, request: Request):
    tenant_id = _tenant_from_request(request, body.tenant_id)
    row = get_dynamic_dashboard(dashboard_id)
    if not row or row.get("status") == "deleted" or str(row.get("tenant_id") or "") != tenant_id:
        raise HTTPException(status_code=404, detail="Dashboard was not found.")
    if body.snapshot is not None:
        updated = update_dynamic_dashboard_snapshot(tenant_id, dashboard_id, body.snapshot)
        return {
            "success": True,
            "mode": "snapshot_updated",
            "dashboard": _visible_dashboard(updated),
            "url": _dashboard_link(dashboard_id),
        }
    return {
        "success": True,
        "mode": "refresh_plan",
        "dashboard": _visible_dashboard(row),
        "refresh_status": _refresh_status(row),
        "refresh_steps": _refresh_steps(row),
        "next_step": "Run each refresh_step, merge the result into one snapshot, then call this endpoint again with snapshot.",
    }


@router.post("/{dashboard_id}/delete")
async def remove_dashboard(dashboard_id: str, body: DynamicDashboardSnapshotRequest, request: Request):
    tenant_id = _tenant_from_request(request, body.tenant_id)
    row = delete_dynamic_dashboard(tenant_id, dashboard_id)
    if not row:
        raise HTTPException(status_code=404, detail="Dashboard was not found.")
    return {"success": True, "dashboard_id": dashboard_id}


@router.get("/{dashboard_id}/data")
async def dashboard_data(dashboard_id: str):
    row = get_dynamic_dashboard(dashboard_id)
    if not row or row.get("status") == "deleted":
        raise HTTPException(status_code=404, detail="Dashboard was not found.")
    return {
        "dashboard_id": dashboard_id,
        "title": row.get("title"),
        "description": row.get("description"),
        "config": row.get("config") or {},
        "snapshot": row.get("snapshot") or {},
        "refresh_policy": row.get("refresh_policy") or {},
        "last_refreshed_at": row.get("last_refreshed_at"),
        "updated_at": row.get("updated_at"),
        "refresh_status": _refresh_status(row),
        "refresh_steps": _refresh_steps(row) if _refresh_status(row).get("stale") else [],
    }


def _dashboard_html(row: dict) -> str:
    title = escape(str(row.get("title") or "Dashboard"))
    description = escape(str(row.get("description") or ""))
    payload = dumps(
        {
            "dashboard_id": row.get("dashboard_id"),
            "title": row.get("title"),
            "description": row.get("description"),
            "config": row.get("config") or {},
            "snapshot": row.get("snapshot") or {},
            "last_refreshed_at": row.get("last_refreshed_at"),
            "refresh_status": _refresh_status(row),
        },
        ensure_ascii=False,
    )
    return f"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{title}</title>
<style>
body {{ margin:0; font-family: Arial, sans-serif; background:#f6f8fb; color:#172033; }}
.shell {{ max-width:1320px; margin:auto; padding:24px; }}
.hero {{ background:#111827; color:white; border-radius:14px; padding:24px; display:flex; justify-content:space-between; gap:16px; align-items:flex-start; }}
.hero h1 {{ margin:0 0 8px; font-size:28px; }}
.muted {{ color:#667085; }}
.hero .muted {{ color:#cbd5e1; }}
.filters,.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:14px; margin-top:18px; }}
.panel {{ background:white; border:1px solid #e5e7eb; border-radius:12px; padding:16px; box-shadow:0 8px 24px rgba(15,23,42,.05); }}
.kpi .value {{ font-size:30px; font-weight:800; margin-top:10px; }}
label {{ display:block; font-size:12px; color:#475467; margin-bottom:6px; }}
input,select {{ width:100%; box-sizing:border-box; padding:10px; border:1px solid #d0d5dd; border-radius:8px; }}
table {{ width:100%; border-collapse:collapse; margin-top:10px; font-size:14px; }}
th,td {{ border-bottom:1px solid #edf0f5; padding:10px; text-align:right; }}
th {{ color:#475467; background:#f9fafb; }}
.bar {{ height:10px; background:#2563eb; border-radius:999px; min-width:4px; }}
.actions {{ display:flex; gap:10px; align-items:center; }}
button,a.button {{ border:0; border-radius:8px; padding:10px 13px; background:#2563eb; color:white; text-decoration:none; cursor:pointer; }}
@media(max-width:720px) {{ .hero {{ display:block; }} .shell {{ padding:14px; }} }}
</style>
</head>
<body>
<div class="shell">
  <section class="hero">
    <div><h1>{title}</h1><div class="muted">{description}</div><div id="refreshMeta" class="muted"></div></div>
    <div class="actions"><button onclick="loadDashboard()">Refresh view</button></div>
  </section>
  <section id="filters" class="filters"></section>
  <section id="widgets" class="grid"></section>
</div>
<script>
const initialPayload = {payload};
let dashboard = initialPayload;
function valueFromSnapshot(key) {{
  const s = dashboard.snapshot || {{}};
  if (s[key] !== undefined) return s[key];
  if ((s.kpis || {{}})[key] !== undefined) return s.kpis[key];
  for (const value of Object.values(s)) {{
    if (value && !Array.isArray(value) && typeof value === "object" && value[key] !== undefined) return value[key];
  }}
  return "";
}}
function sourceData(widget) {{
  const s = dashboard.snapshot || {{}};
  if (widget.source && s[widget.source] !== undefined) return s[widget.source];
  if (widget.metric) {{
    for (const value of Object.values(s)) {{
      if (value && !Array.isArray(value) && typeof value === "object" && value[widget.metric] !== undefined) return value;
      if (Array.isArray(value) && value.some(row => row && row[widget.metric] !== undefined)) return value;
    }}
  }}
  return s[widget.id] ?? [];
}}
function rowsFromData(data) {{
  if (Array.isArray(data)) return data;
  if (data && typeof data === "object") return [data];
  if (data === undefined || data === null || data === "") return [];
  return [{{ value: data }}];
}}
function renderFilters() {{
  const box = document.getElementById("filters");
  const filters = (dashboard.config && dashboard.config.filters) || [];
  box.innerHTML = filters.map(f => {{
    const label = f.label || f.key;
    if (f.type === "date_range") return `<div class="panel"><label>${{label}}</label><input type="date"><input type="date" style="margin-top:8px"></div>`;
    const options = (f.options || []).map(o => `<option value="${{o.value ?? o.label}}">${{o.label ?? o.value}}</option>`).join("");
    if (f.type === "select") return `<div class="panel"><label>${{label}}</label><select><option value="">All</option>${{options}}</select></div>`;
    return `<div class="panel"><label>${{label}}</label><input value="${{f.default ?? ""}}"></div>`;
  }}).join("");
}}
function tableHtml(widget, rows) {{
  rows = rowsFromData(rows);
  const columns = widget.columns && widget.columns.length ? widget.columns : Object.keys(rows[0] || {{}});
  return `<table><thead><tr>${{columns.map(c=>`<th>${{c}}</th>`).join("")}}</tr></thead><tbody>${{rows.map(r=>`<tr>${{columns.map(c=>`<td>${{r[c] ?? ""}}</td>`).join("")}}</tr>`).join("")}}</tbody></table>`;
}}
function renderWidget(widget) {{
  const data = sourceData(widget);
  if (widget.type === "kpi") return `<div class="panel kpi"><div class="muted">${{widget.title}}</div><div class="value">${{valueFromSnapshot(widget.metric || widget.id)}}</div></div>`;
  if (widget.type === "text") return `<div class="panel"><h3>${{widget.title}}</h3><p>${{widget.config?.text || valueFromSnapshot(widget.id) || ""}}</p></div>`;
  if (widget.type === "funnel") {{
    const rows = rowsFromData(data);
    const first = rows[0] || {{}};
    const entries = Object.entries(first).filter(([k,v]) => typeof v === "number" || (!isNaN(Number(v)) && String(v).trim() !== ""));
    const max = Math.max(1, ...entries.map(([k,v]) => Number(v || 0)));
    return `<div class="panel"><h3>${{widget.title}}</h3>${{entries.map(([k,v])=>`<div style="margin:10px 0"><div>${{k}} - ${{v}}</div><div class="bar" style="width:${{Math.max(3, Number(v || 0)/max*100)}}%"></div></div>`).join("") || tableHtml(widget, data)}}</div>`;
  }}
  if (widget.type === "bar") {{
    const rows = rowsFromData(data).slice(0, 12);
    const metric = widget.metric || Object.keys(rows[0] || {{}}).find(k => typeof rows[0][k] === "number");
    const label = (widget.dimensions || [])[0] || Object.keys(rows[0] || {{}})[0];
    const max = Math.max(1, ...rows.map(r => Number(r[metric] || 0)));
    return `<div class="panel"><h3>${{widget.title}}</h3>${{rows.map(r=>`<div style="margin:10px 0"><div>${{r[label] ?? ""}} - ${{r[metric] ?? 0}}</div><div class="bar" style="width:${{Math.max(3, Number(r[metric] || 0)/max*100)}}%"></div></div>`).join("")}}</div>`;
  }}
  return `<div class="panel"><h3>${{widget.title}}</h3>${{tableHtml(widget, data)}}</div>`;
}}
function renderWidgets() {{
  const widgets = (dashboard.config && dashboard.config.widgets) || [];
  document.getElementById("widgets").innerHTML = widgets.map(renderWidget).join("");
  const status = dashboard.refresh_status || {{}};
  const suffix = status.stale ? " - needs refresh" : "";
  document.getElementById("refreshMeta").textContent = dashboard.last_refreshed_at ? `Last refreshed: ${{dashboard.last_refreshed_at}}${{suffix}}` : `Live dashboard${{suffix}}`;
}}
async function loadDashboard() {{
  const res = await fetch(`/dynamic_dashboards/${{dashboard.dashboard_id}}/data`);
  dashboard = await res.json();
  renderFilters();
  renderWidgets();
}}
renderFilters();
renderWidgets();
</script>
</body>
</html>"""


@router.get("/{dashboard_id}", response_class=HTMLResponse)
async def view_dashboard(dashboard_id: str):
    row = get_dynamic_dashboard(dashboard_id)
    if not row or row.get("status") == "deleted":
        raise HTTPException(status_code=404, detail="Dashboard was not found.")
    return HTMLResponse(_dashboard_html(row))
