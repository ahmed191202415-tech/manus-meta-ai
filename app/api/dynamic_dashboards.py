from html import escape
from json import dumps
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.config import PUBLIC_BASE_URL
from app.core.oauth_store import (
    create_dashboard_dataset,
    create_dynamic_dashboard,
    delete_dashboard_dataset,
    delete_dashboard_dataset_records,
    delete_dynamic_dashboard,
    get_app_token_data,
    get_dashboard_dataset,
    get_dynamic_dashboard,
    list_dashboard_dataset_records,
    list_dashboard_datasets,
    list_dynamic_dashboards,
    upsert_dashboard_dataset_records,
    update_dynamic_dashboard_config,
    update_dynamic_dashboard_snapshot,
)
from app.schemas.dynamic_dashboard_requests import (
    DashboardDatasetCreateRequest,
    DashboardDatasetDeleteRecordsRequest,
    DashboardDatasetQueryRequest,
    DashboardDatasetRecordsRequest,
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
    for key in ("render_mode", "html", "css", "javascript", "data_contract"):
        value = getattr(body, key, None)
        if value is not None:
            config[key] = value
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
        elif source_type in {"dataset", "backend_dataset"}:
            steps.append(
                {
                    "source": name,
                    "tool": "/tools/dashboards",
                    "body": {
                        "action": "query_dataset",
                        "dataset_id": source.get("dataset_id") or query.get("dataset_id"),
                        **query,
                    },
                }
            )
        else:
            steps.append({"source": name, "tool": "manual_snapshot", "body": query})
    return steps


@router.post("/create")
async def create_dashboard(body: DynamicDashboardCreateRequest, request: Request):
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


async def create_dataset(body: DashboardDatasetCreateRequest, request: Request):
    tenant_id = _tenant_from_request(request, body.tenant_id)
    if body.dashboard_id:
        dashboard = get_dynamic_dashboard(body.dashboard_id)
        if not dashboard or str(dashboard.get("tenant_id") or "") != tenant_id:
            raise HTTPException(status_code=404, detail="Dashboard was not found.")
    row = create_dashboard_dataset(
        tenant_id=tenant_id,
        dashboard_id=body.dashboard_id,
        name=body.name,
        description=body.description,
        schema=body.dataset_schema,
        metadata=body.metadata,
    )
    return {"success": True, "dataset": row}


async def list_datasets(request: Request, tenant_id: str | None = None, dashboard_id: str | None = None, limit: int = 100):
    resolved_tenant_id = _tenant_from_request(request, tenant_id)
    return {
        "tenant_id": resolved_tenant_id,
        "datasets": list_dashboard_datasets(resolved_tenant_id, dashboard_id=dashboard_id, limit=limit),
    }


async def upsert_dataset_records(body: DashboardDatasetRecordsRequest, request: Request):
    tenant_id = _tenant_from_request(request, body.tenant_id)
    dataset = get_dashboard_dataset(tenant_id, body.dataset_id)
    if not dataset or dataset.get("status") == "deleted":
        raise HTTPException(status_code=404, detail="Dataset was not found.")
    rows = upsert_dashboard_dataset_records(
        tenant_id,
        body.dataset_id,
        body.records,
        external_key_field=body.external_key_field,
    )
    return {
        "success": True,
        "dataset_id": body.dataset_id,
        "upserted_count": len(rows),
        "records": rows,
    }


async def query_dataset(body: DashboardDatasetQueryRequest, request: Request):
    tenant_id = _tenant_from_request(request, body.tenant_id)
    dataset = get_dashboard_dataset(tenant_id, body.dataset_id)
    if not dataset or dataset.get("status") == "deleted":
        raise HTTPException(status_code=404, detail="Dataset was not found.")
    raw_rows = list_dashboard_dataset_records(
        tenant_id,
        body.dataset_id,
        limit=min(max(body.limit + body.offset, body.limit), 1000),
        offset=0,
    )
    rows = [_dataset_record_view(item) for item in raw_rows]
    rows = [item for item in rows if _record_matches(item, body.filters, body.search)]
    if body.sort_by:
        rows.sort(
            key=lambda item: _sort_value(_nested_value(item, body.sort_by)),
            reverse=body.sort_order == "desc",
        )
    paged = rows[body.offset : body.offset + body.limit]
    return {
        "dataset": dataset,
        "records": paged,
        "row_count": len(paged),
        "matched_count": len(rows),
        "filters": body.filters,
        "search": body.search,
    }


async def remove_dataset_records(body: DashboardDatasetDeleteRecordsRequest, request: Request):
    tenant_id = _tenant_from_request(request, body.tenant_id)
    dataset = get_dashboard_dataset(tenant_id, body.dataset_id)
    if not dataset or dataset.get("status") == "deleted":
        raise HTTPException(status_code=404, detail="Dataset was not found.")
    delete_dashboard_dataset_records(
        tenant_id,
        body.dataset_id,
        record_ids=body.record_ids,
        external_keys=body.external_keys,
    )
    return {"success": True, "dataset_id": body.dataset_id}


async def remove_dataset(dataset_id: str, request: Request, tenant_id: str | None = None):
    resolved_tenant_id = _tenant_from_request(request, tenant_id)
    row = delete_dashboard_dataset(resolved_tenant_id, dataset_id)
    if not row:
        raise HTTPException(status_code=404, detail="Dataset was not found.")
    return {"success": True, "dataset": row}


def _dataset_record_view(row: dict) -> dict:
    data = dict(row.get("data") or {})
    return {
        **data,
        "_record_id": row.get("record_id"),
        "_external_key": row.get("external_key"),
        "_created_at": row.get("created_at"),
        "_updated_at": row.get("updated_at"),
    }


def _nested_value(item: dict, path: str):
    value = item
    for part in str(path or "").split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _record_matches(item: dict, filters: dict, search: str | None) -> bool:
    for key, expected in (filters or {}).items():
        actual = _nested_value(item, key)
        if isinstance(expected, list):
            if actual not in expected:
                return False
        elif isinstance(expected, dict):
            if "contains" in expected and str(expected["contains"]).casefold() not in str(actual or "").casefold():
                return False
            if "gte" in expected and (actual is None or actual < expected["gte"]):
                return False
            if "lte" in expected and (actual is None or actual > expected["lte"]):
                return False
        elif actual != expected:
            return False
    if search:
        return str(search).casefold() in dumps(item, ensure_ascii=False).casefold()
    return True


def _sort_value(value):
    if value is None:
        return (1, "")
    if isinstance(value, (int, float)):
        return (0, float(value))
    return (0, str(value).casefold())


def _linked_dataset_snapshot(row: dict) -> dict:
    tenant_id = str(row.get("tenant_id") or "")
    dashboard_id = str(row.get("dashboard_id") or "")
    warnings = []
    try:
        datasets = list_dashboard_datasets(tenant_id, dashboard_id=dashboard_id, limit=100)
    except Exception as exc:
        return {
            "snapshot": {},
            "datasets": [],
            "warnings": [
                {
                    "source": "dashboard_datasets",
                    "message": "Linked dashboard datasets are unavailable. Run supabase/multi_tenant_schema.sql to enable dataset-backed dashboards.",
                    "detail": str(exc),
                }
            ],
        }
    config_sources = (row.get("config") or {}).get("data_sources") or []
    configured_ids = {
        str(source.get("dataset_id") or (source.get("query") or {}).get("dataset_id") or "")
        for source in config_sources
        if source.get("source") in {"dataset", "backend_dataset"}
    }
    for dataset_id in configured_ids:
        if dataset_id and not any(str(item.get("dataset_id")) == dataset_id for item in datasets):
            try:
                dataset = get_dashboard_dataset(tenant_id, dataset_id)
            except Exception as exc:
                warnings.append(
                    {
                        "source": "dashboard_dataset",
                        "dataset_id": dataset_id,
                        "message": "A configured dashboard dataset could not be loaded.",
                        "detail": str(exc),
                    }
                )
                continue
            if dataset and dataset.get("status") != "deleted":
                datasets.append(dataset)
    snapshot = {}
    details = []
    for dataset in datasets:
        dataset_id = str(dataset.get("dataset_id") or "")
        try:
            records = [
                _dataset_record_view(item)
                for item in list_dashboard_dataset_records(tenant_id, dataset_id, limit=500)
            ]
        except Exception as exc:
            warnings.append(
                {
                    "source": "dashboard_dataset_records",
                    "dataset_id": dataset_id,
                    "message": "Dashboard dataset records could not be loaded.",
                    "detail": str(exc),
                }
            )
            records = []
        name = str(dataset.get("name") or dataset_id)
        snapshot[dataset_id] = records
        snapshot[name] = records
        details.append({**dataset, "records": records, "row_count": len(records)})
    return {"snapshot": snapshot, "datasets": details, "warnings": warnings}


@router.get("/{dashboard_id}/data")
async def dashboard_data(dashboard_id: str):
    row = get_dynamic_dashboard(dashboard_id)
    if not row or row.get("status") == "deleted":
        raise HTTPException(status_code=404, detail="Dashboard was not found.")
    dataset_data = _linked_dataset_snapshot(row)
    snapshot = {**(row.get("snapshot") or {}), **dataset_data["snapshot"]}
    return {
        "dashboard_id": dashboard_id,
        "title": row.get("title"),
        "description": row.get("description"),
        "config": row.get("config") or {},
        "snapshot": snapshot,
        "datasets": dataset_data["datasets"],
        "warnings": dataset_data.get("warnings", []),
        "refresh_policy": row.get("refresh_policy") or {},
        "last_refreshed_at": row.get("last_refreshed_at"),
        "updated_at": row.get("updated_at"),
        "refresh_status": _refresh_status(row),
        "refresh_steps": _refresh_steps(row) if _refresh_status(row).get("stale") else [],
    }


def _dashboard_html(row: dict) -> str:
    title = escape(str(row.get("title") or "Dashboard"))
    description = escape(str(row.get("description") or ""))
    dataset_data = _linked_dataset_snapshot(row)
    payload = dumps(
        {
            "dashboard_id": row.get("dashboard_id"),
            "title": row.get("title"),
            "description": row.get("description"),
            "config": row.get("config") or {},
            "snapshot": {**(row.get("snapshot") or {}), **dataset_data["snapshot"]},
            "datasets": dataset_data["datasets"],
            "warnings": dataset_data.get("warnings", []),
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
.status-strip {{ display:flex; flex-wrap:wrap; gap:10px; margin-top:14px; align-items:center; }}
.badge {{ display:inline-flex; align-items:center; gap:7px; border-radius:999px; padding:7px 11px; font-size:13px; background:#eef2ff; color:#1e3a8a; }}
.badge.ok {{ background:#dcfce7; color:#166534; }}
.badge.warn {{ background:#fef3c7; color:#92400e; }}
.badge.error {{ background:#fee2e2; color:#991b1b; }}
.dot {{ width:8px; height:8px; border-radius:999px; background:currentColor; }}
.filters {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:14px; margin-top:18px; }}
.grid {{ display:block; margin-top:18px; }}
.kpi-strip {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:14px; margin-bottom:14px; }}
.content-grid {{ display:grid; grid-template-columns:repeat(12,minmax(0,1fr)); gap:14px; align-items:start; }}
.panel {{ background:white; border:1px solid #e5e7eb; border-radius:12px; padding:16px; box-shadow:0 8px 24px rgba(15,23,42,.05); min-width:0; overflow:hidden; }}
.widget-table {{ grid-column:1 / -1; }}
.widget-funnel,.widget-bar,.widget-text {{ grid-column:span 6; }}
.widget-kpi {{ min-height:92px; }}
.kpi .value {{ font-size:30px; font-weight:800; margin-top:10px; }}
label {{ display:block; font-size:12px; color:#475467; margin-bottom:6px; }}
input,select {{ width:100%; box-sizing:border-box; padding:10px; border:1px solid #d0d5dd; border-radius:8px; }}
.table-wrap {{ width:100%; overflow-x:auto; overflow-y:hidden; margin-top:10px; border:1px solid #edf0f5; border-radius:10px; }}
table {{ width:100%; min-width:720px; border-collapse:collapse; font-size:14px; direction:ltr; }}
th,td {{ border-bottom:1px solid #edf0f5; padding:10px; text-align:left; vertical-align:top; white-space:normal; overflow-wrap:anywhere; }}
th {{ color:#475467; background:#f9fafb; }}
.bar {{ height:10px; background:#2563eb; border-radius:999px; min-width:4px; }}
.actions {{ display:flex; gap:10px; align-items:center; }}
button,a.button {{ border:0; border-radius:10px; padding:11px 15px; background:#2563eb; color:white; text-decoration:none; cursor:pointer; font-weight:700; display:inline-flex; align-items:center; gap:8px; box-shadow:0 8px 18px rgba(37,99,235,.22); transition:transform .12s ease, opacity .12s ease, background .12s ease; }}
button:hover,a.button:hover {{ background:#1d4ed8; transform:translateY(-1px); }}
button:active,a.button:active {{ transform:translateY(0); opacity:.86; }}
button[disabled] {{ cursor:wait; opacity:.72; transform:none; }}
.spinner {{ width:14px; height:14px; border:2px solid rgba(255,255,255,.45); border-top-color:white; border-radius:999px; animation:spin .8s linear infinite; }}
.empty {{ padding:14px; border:1px dashed #cbd5e1; border-radius:10px; color:#667085; background:#f8fafc; }}
@keyframes spin {{ to {{ transform:rotate(360deg); }} }}
@media(max-width:920px) {{ .widget-funnel,.widget-bar,.widget-text {{ grid-column:1 / -1; }} }}
@media(max-width:720px) {{ .hero {{ display:block; }} .shell {{ padding:14px; }} .content-grid {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body>
<div class="shell">
  <section class="hero">
    <div>
      <h1>{title}</h1>
      <div class="muted">{description}</div>
      <div class="status-strip">
        <span id="refreshBadge" class="badge"><i class="dot"></i><span>Checking data</span></span>
        <span id="refreshMeta" class="muted"></span>
      </div>
    </div>
    <div class="actions"><button id="refreshButton" onclick="loadDashboard(true)"><span id="refreshIcon">↻</span><span id="refreshLabel">Refresh</span></button></div>
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
  const sourceKey = String(widget.source || "").toLowerCase().replace(/[^a-z0-9]/g, "");
  if (sourceKey) {{
    for (const [key, value] of Object.entries(s)) {{
      const cleanKey = String(key).toLowerCase().replace(/[^a-z0-9]/g, "");
      if (cleanKey && (cleanKey.includes(sourceKey) || sourceKey.includes(cleanKey))) return value;
      if (sourceKey.includes("meta") && cleanKey.includes("meta")) return value;
      if (sourceKey.includes("clarity") && cleanKey.includes("clarity")) return value;
      if ((sourceKey.includes("ga4") || sourceKey.includes("journey")) && (cleanKey.includes("ga4") || cleanKey.includes("journey") || cleanKey.includes("whatsapp") || cleanKey.includes("register"))) return value;
    }}
  }}
  const dimensions = widget.dimensions || [];
  if (dimensions.length) {{
    for (const value of Object.values(s)) {{
      if (Array.isArray(value) && value.some(row => row && dimensions.some(dim => row[dim] !== undefined))) return value;
      if (value && !Array.isArray(value) && typeof value === "object" && dimensions.some(dim => value[dim] !== undefined)) return value;
    }}
  }}
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
function formatDateTime(value) {{
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ar-EG", {{
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Africa/Cairo"
  }}).format(date);
}}
function setRefreshLoading(isLoading) {{
  const button = document.getElementById("refreshButton");
  const icon = document.getElementById("refreshIcon");
  const label = document.getElementById("refreshLabel");
  if (!button || !icon || !label) return;
  button.disabled = isLoading;
  icon.innerHTML = isLoading ? '<span class="spinner"></span>' : '↻';
  label.textContent = isLoading ? "Refreshing..." : "Refresh";
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
  if (!rows.length) return '<div class="empty">No data available for this widget yet.</div>';
  const columns = widget.columns && widget.columns.length ? widget.columns : Object.keys(rows[0] || {{}});
  return `<div class="table-wrap"><table><thead><tr>${{columns.map(c=>`<th>${{c}}</th>`).join("")}}</tr></thead><tbody>${{rows.map(r=>`<tr>${{columns.map(c=>`<td dir="auto">${{r[c] ?? ""}}</td>`).join("")}}</tr>`).join("")}}</tbody></table></div>`;
}}
function renderWidget(widget) {{
  const data = sourceData(widget);
  if (widget.type === "kpi") return `<div class="panel kpi widget-kpi"><div class="muted">${{widget.title}}</div><div class="value">${{valueFromSnapshot(widget.metric || widget.id) || "—"}}</div></div>`;
  if (widget.type === "text") return `<div class="panel widget-text"><h3>${{widget.title}}</h3><p>${{widget.config?.text || valueFromSnapshot(widget.id) || ""}}</p></div>`;
  if (widget.type === "funnel") {{
    const rows = rowsFromData(data);
    const first = rows[0] || {{}};
    const entries = Object.entries(first).filter(([k,v]) => typeof v === "number" || (!isNaN(Number(v)) && String(v).trim() !== ""));
    const max = Math.max(1, ...entries.map(([k,v]) => Number(v || 0)));
    return `<div class="panel widget-funnel"><h3>${{widget.title}}</h3>${{entries.map(([k,v])=>`<div style="margin:10px 0"><div>${{k}} - ${{v}}</div><div class="bar" style="width:${{Math.max(3, Number(v || 0)/max*100)}}%"></div></div>`).join("") || tableHtml(widget, data)}}</div>`;
  }}
  if (widget.type === "bar") {{
    const rows = rowsFromData(data).slice(0, 12);
    const metric = widget.metric || Object.keys(rows[0] || {{}}).find(k => typeof rows[0][k] === "number");
    const label = (widget.dimensions || [])[0] || Object.keys(rows[0] || {{}})[0];
    const max = Math.max(1, ...rows.map(r => Number(r[metric] || 0)));
    return `<div class="panel widget-bar"><h3>${{widget.title}}</h3>${{rows.map(r=>`<div style="margin:10px 0"><div>${{r[label] ?? ""}} - ${{r[metric] ?? 0}}</div><div class="bar" style="width:${{Math.max(3, Number(r[metric] || 0)/max*100)}}%"></div></div>`).join("") || '<div class="empty">No data available for this chart yet.</div>'}}</div>`;
  }}
  return `<div class="panel widget-table"><h3>${{widget.title}}</h3>${{tableHtml(widget, data)}}</div>`;
}}
function renderWidgets() {{
  const widgets = (dashboard.config && dashboard.config.widgets) || [];
  const kpis = widgets.filter(w => w.type === "kpi");
  const rest = widgets.filter(w => w.type !== "kpi");
  document.getElementById("widgets").innerHTML = `<section class="kpi-strip">${{kpis.map(renderWidget).join("")}}</section><section class="content-grid">${{rest.map(renderWidget).join("")}}</section>`;
  const status = dashboard.refresh_status || {{}};
  const badge = document.getElementById("refreshBadge");
  const badgeText = status.stale ? "Needs refresh" : "Up to date";
  badge.className = `badge ${{status.stale ? "warn" : "ok"}}`;
  badge.innerHTML = `<i class="dot"></i><span>${{badgeText}}</span>`;
  const formatted = formatDateTime(dashboard.last_refreshed_at);
  document.getElementById("refreshMeta").textContent = formatted ? `Last refresh: ${{formatted}} Cairo time` : "No refresh time saved yet";
}}
async function loadDashboard(showFeedback=false) {{
  setRefreshLoading(true);
  try {{
    const res = await fetch(`/dynamic_dashboards/${{dashboard.dashboard_id}}/data`, {{ cache: "no-store" }});
    if (!res.ok) throw new Error(await res.text());
    dashboard = await res.json();
    renderFilters();
    renderWidgets();
  }} catch (error) {{
    const badge = document.getElementById("refreshBadge");
    badge.className = "badge error";
    badge.innerHTML = `<i class="dot"></i><span>Refresh failed</span>`;
    if (showFeedback) alert("Could not refresh dashboard data.");
  }} finally {{
    setRefreshLoading(false);
  }}
}}
renderFilters();
renderWidgets();
</script>
</body>
</html>"""


def _code_dashboard_html(row: dict) -> str:
    config = row.get("config") or {}
    dataset_data = _linked_dataset_snapshot(row)
    dashboard = {
        "dashboard_id": row.get("dashboard_id"),
        "title": row.get("title"),
        "description": row.get("description"),
        "data_contract": config.get("data_contract") or {},
        "snapshot": {**(row.get("snapshot") or {}), **dataset_data["snapshot"]},
        "datasets": dataset_data["datasets"],
    }
    dashboard_json = dumps(dashboard, ensure_ascii=False).replace("</script", "<\\/script")
    html = str(config.get("html") or "<main id=\"app\"></main>")
    css = str(config.get("css") or "")
    javascript = str(config.get("javascript") or "").replace("</script", "<\\/script")
    title = escape(str(row.get("title") or "Dashboard"))
    return f"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{title}</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
* {{ box-sizing:border-box; }}
body {{ margin:0; font-family:Arial,sans-serif; background:#f6f8fb; color:#172033; }}
{css}
</style>
</head>
<body>
{html}
<script>
window.ALLINGPT_DASHBOARD = {dashboard_json};
window.ALLINGPT = {{
  dashboard: window.ALLINGPT_DASHBOARD,
  snapshot: window.ALLINGPT_DASHBOARD.snapshot || {{}},
  datasets: window.ALLINGPT_DASHBOARD.datasets || [],
  async reload() {{
    const response = await fetch("/dynamic_dashboards/" + encodeURIComponent(this.dashboard.dashboard_id) + "/data", {{cache:"no-store"}});
    if (!response.ok) throw new Error(await response.text());
    const data = await response.json();
    this.dashboard = data;
    this.snapshot = data.snapshot || {{}};
    this.datasets = data.datasets || [];
    return data;
  }},
  async runQuery(queryId, filters={{}}, context={{}}) {{
    const response = await fetch("/api/dashboard-runtime/query", {{
      method:"POST",
      headers:{{"Content-Type":"application/json"}},
      body:JSON.stringify({{
        dashboard_id:this.dashboard.dashboard_id,
        query_id:queryId,
        filters,
        context:{{...context,data_contract:this.dashboard.data_contract || {{}}}}
      }})
    }});
    if (!response.ok) throw new Error(await response.text());
    return await response.json();
  }},
  dataset(nameOrId) {{
    return this.snapshot[nameOrId] || [];
  }}
}};
{javascript}
</script>
</body>
</html>"""


@router.get("/{dashboard_id}", response_class=HTMLResponse)
async def view_dashboard(dashboard_id: str):
    row = get_dynamic_dashboard(dashboard_id)
    if not row or row.get("status") == "deleted":
        raise HTTPException(status_code=404, detail="Dashboard was not found.")
    if str((row.get("config") or {}).get("render_mode") or "manifest") == "code":
        return HTMLResponse(_code_dashboard_html(row))
    return HTMLResponse(_dashboard_html(row))
