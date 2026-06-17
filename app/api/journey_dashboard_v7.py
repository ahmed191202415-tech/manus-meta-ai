from json import dumps
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from app.config import PUBLIC_BASE_URL
from app.analytics.dashboard_engine import (
    CONNECTOR_REGISTRY,
    DEFAULT_DASHBOARD_DEFINITION,
    METRIC_DICTIONARY,
    build_fallback_funnel,
    build_mixed_funnel,
    build_query_plan,
    comparison,
    filter_options,
    stage_detail,
    trend,
)
from app.core.auth import resolve_access_token
from app.core.meta_client import meta_call

router = APIRouter(tags=["journey-dashboard-v7"])

_DEFINITIONS = {DEFAULT_DASHBOARD_DEFINITION["dashboard_id"]: DEFAULT_DASHBOARD_DEFINITION}
META_DASHBOARD_FIELDS = (
    "campaign_id,campaign_name,spend,impressions,reach,clicks,inline_link_clicks,"
    "unique_inline_link_clicks,unique_ctr,actions,date_start,date_stop"
)


class DashboardDefinitionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    dashboard_id: str = Field("custom_dashboard", description="Stable dashboard id.")
    title: str | None = Field(None, description="Dashboard title.")
    description: str | None = Field(None, description="Optional dashboard description.")
    filters: list[dict[str, Any]] = Field(default_factory=list, description="Dashboard filter definitions.")
    data_sources: dict[str, Any] = Field(default_factory=dict, description="Meta, GA4, Clarity, or other source config.")
    metrics: dict[str, Any] = Field(default_factory=dict, description="Metric definitions and event mappings.")
    charts: list[dict[str, Any]] = Field(default_factory=list, description="Chart, table, and interaction definitions.")
    stages: list[dict[str, Any]] = Field(default_factory=list, description="Ordered funnel or journey stages.")
    widgets: list[dict[str, Any]] = Field(default_factory=list, description="Renderer widgets and their placement.")
    layout: dict[str, Any] = Field(default_factory=dict, description="Optional renderer layout hints.")
    interactions: list[dict[str, Any]] = Field(default_factory=list, description="Cross-filtering or drilldown rules.")
    runtime_queries: dict[str, Any] = Field(default_factory=dict, description="Named runtime query definitions.")
    formulas: dict[str, Any] = Field(default_factory=dict, description="Formula definitions for calculated metrics.")


class DashboardRuntimeQueryRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    dashboard_id: str = Field("customer_journey", description="Dashboard definition id.")
    query_id: str = Field("journey_funnel", description="Query to run, such as journey_funnel or journey_trend.")
    filters: dict[str, Any] = Field(default_factory=dict, description="Date, campaign, ad set, ad, device, and placement filters.")
    context: dict[str, Any] = Field(default_factory=dict, description="Optional runtime context.")


class DashboardDefinitionUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    title: str | None = Field(None, description="Dashboard title.")
    description: str | None = Field(None, description="Optional dashboard description.")
    filters: list[dict[str, Any]] = Field(default_factory=list, description="Dashboard filter definitions.")
    data_sources: dict[str, Any] = Field(default_factory=dict, description="Meta, GA4, Clarity, or other source config.")
    metrics: dict[str, Any] = Field(default_factory=dict, description="Metric definitions and event mappings.")
    charts: list[dict[str, Any]] = Field(default_factory=list, description="Chart, table, and interaction definitions.")
    stages: list[dict[str, Any]] = Field(default_factory=list, description="Ordered funnel or journey stages.")
    widgets: list[dict[str, Any]] = Field(default_factory=list, description="Renderer widgets and their placement.")
    layout: dict[str, Any] = Field(default_factory=dict, description="Optional renderer layout hints.")
    interactions: list[dict[str, Any]] = Field(default_factory=list, description="Cross-filtering or drilldown rules.")
    runtime_queries: dict[str, Any] = Field(default_factory=dict, description="Named runtime query definitions.")
    formulas: dict[str, Any] = Field(default_factory=dict, description="Formula definitions for calculated metrics.")


class ComparisonEntity(BaseModel):
    type: str = Field("campaign", description="Entity type: campaign, adset, or ad.")
    id: str = Field(..., description="Meta entity id.")
    name: str | None = Field(None, description="Optional display name.")


class JourneyComparisonRequest(BaseModel):
    entities: list[ComparisonEntity] = Field(default_factory=list, description="Entities to compare.")
    stage_id: str = Field("register_page", description="Journey stage to compare.")
    metric: str = Field("cost", description="Metric to rank by.")
    sort: str = Field("lowest_cost", description="Sort mode.")
    date_from: str | None = Field(None, description="Start date.")
    date_to: str | None = Field(None, description="End date.")


def _dashboard_url(dashboard_id: str) -> str:
    path = f"/dashboards/custom/{dashboard_id}"
    return f"{PUBLIC_BASE_URL}{path}" if PUBLIC_BASE_URL else path


@router.get("/journey-dashboard/v7", response_class=HTMLResponse)
async def journey_dashboard_v7():
    definition_json = dumps(DEFAULT_DASHBOARD_DEFINITION, ensure_ascii=False)
    return HTMLResponse(f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Customer Journey Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
:root {{ --bg:#f5f7fb; --panel:#fff; --line:#dfe5ef; --text:#111827; --muted:#667085; --blue:#2563eb; --red:#dc2626; --green:#16a34a; --amber:#d97706; }}
body {{ margin:0; font-family:Arial, sans-serif; background:var(--bg); color:var(--text); }}
.shell {{ max-width:1440px; margin:0 auto; padding:22px; }}
.top {{ background:#111827; color:#fff; border-radius:12px; padding:20px; display:flex; justify-content:space-between; gap:18px; align-items:flex-start; }}
h1 {{ margin:0 0 8px; font-size:26px; }}
h2,h3 {{ margin:0 0 12px; }}
.muted {{ color:var(--muted); }}
.top .muted {{ color:#cbd5e1; }}
.filters {{ display:grid; grid-template-columns:repeat(6,minmax(150px,1fr)); gap:12px; margin:16px 0; }}
.panel {{ background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:16px; box-shadow:0 8px 22px rgba(15,23,42,.05); min-width:0; }}
label {{ display:block; color:var(--muted); font-size:12px; margin-bottom:6px; }}
input,select {{ width:100%; box-sizing:border-box; border:1px solid #cfd7e6; border-radius:8px; padding:10px; background:white; }}
button {{ border:0; border-radius:9px; background:var(--blue); color:white; padding:11px 14px; font-weight:700; cursor:pointer; }}
button.secondary {{ background:#475467; }}
button:disabled {{ opacity:.65; cursor:wait; }}
.kpis {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin-bottom:14px; }}
.kpi .v {{ font-size:26px; font-weight:800; margin-top:8px; }}
.grid {{ display:grid; grid-template-columns:1.15fr .85fr; gap:14px; align-items:start; }}
.wide {{ grid-column:1 / -1; }}
.chart {{ width:100%; height:360px; }}
.small-chart {{ width:100%; height:300px; }}
.stage-row {{ display:grid; grid-template-columns:1fr auto auto auto; gap:10px; padding:10px; border-bottom:1px solid #edf0f5; cursor:pointer; align-items:center; }}
.stage-row:hover {{ background:#f8fafc; }}
.pill {{ display:inline-flex; border-radius:999px; padding:5px 9px; font-size:12px; font-weight:700; }}
.red {{ color:#991b1b; background:#fee2e2; }} .green {{ color:#166534; background:#dcfce7; }} .yellow {{ color:#92400e; background:#fef3c7; }} .neutral {{ color:#344054; background:#edf2f7; }}
.metric-list {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:10px; }}
.metric {{ border:1px solid #edf0f5; border-radius:10px; padding:11px; }}
.src {{ color:var(--muted); font-size:12px; margin-top:4px; }}
table {{ width:100%; border-collapse:collapse; }}
th,td {{ border-bottom:1px solid #edf0f5; padding:10px; text-align:left; vertical-align:top; }}
th {{ background:#f8fafc; color:#475467; }}
.table-wrap {{ overflow-x:auto; }}
.debug {{ display:none; white-space:pre-wrap; background:#0f172a; color:#dbeafe; border-radius:10px; padding:12px; font-size:12px; }}
.loading {{ opacity:.55; pointer-events:none; }}
.error {{ border-color:#fecaca; background:#fff1f2; color:#991b1b; }}
@media(max-width:1100px) {{ .filters,.kpis,.grid {{ grid-template-columns:1fr 1fr; }} }}
@media(max-width:720px) {{ .filters,.kpis,.grid {{ grid-template-columns:1fr; }} .top {{ display:block; }} }}
</style>
</head>
<body>
<div class="shell" id="app">
  <section class="top">
    <div><h1>Customer Journey Intelligence</h1><div class="muted">Definition-driven dashboard runtime: Meta + GA4 + Clarity + calculated journey metrics.</div></div>
    <div><button onclick="reloadAll()">Refresh</button> <button class="secondary" onclick="toggleDebug()">Debug</button></div>
  </section>
  <section class="filters">
    <div class="panel"><label>Date from</label><input id="date_from" type="date" value="2026-06-15"></div>
    <div class="panel"><label>Date to</label><input id="date_to" type="date" value="2026-06-16"></div>
    <div class="panel"><label>Campaign</label><select id="campaign_id"></select></div>
    <div class="panel"><label>Ad Set</label><select id="adset_id"></select></div>
    <div class="panel"><label>Device</label><select id="device"></select></div>
    <div class="panel"><label>Placement</label><select id="placement"></select></div>
  </section>
  <section class="kpis" id="kpis"></section>
  <section id="errorBox"></section>
  <section class="grid">
    <div class="panel"><h2>Conversion Path</h2><div id="pathChart" class="chart"></div><div id="stageRows"></div></div>
    <div class="panel"><h2>Stage Inspector</h2><div id="stageInspector" class="metric-list"></div></div>
    <div class="panel wide"><h2>Trend Analysis Studio</h2>
      <div class="filters" style="grid-template-columns:repeat(4,minmax(140px,1fr));margin-top:0">
        <div><label>Trend from</label><input id="trend_from" type="date" value="2026-06-10"></div>
        <div><label>Trend to</label><input id="trend_to" type="date" value="2026-06-16"></div>
        <div><label>Stage</label><select id="trend_stage"><option value="register_page">Register Page</option><option value="otp">OTP</option><option value="complete_profile">Complete Profile</option></select></div>
        <div><label>Metric</label><select id="trend_metric"><option value="value">Value</option><option value="cost">Cost</option><option value="transition">Transition</option><option value="drop">Drop</option></select></div>
      </div>
      <div id="trendChart" class="small-chart"></div>
    </div>
    <div class="panel"><h2>Drop-off Waterfall</h2><div id="dropChart" class="small-chart"></div></div>
    <div class="panel"><h2>Cost Escalation</h2><div id="costChart" class="small-chart"></div></div>
    <div class="panel wide"><h2>Comparison Lab</h2>
      <div class="filters" style="grid-template-columns:repeat(4,minmax(140px,1fr));margin-top:0">
        <div><label>Stage</label><select id="compare_stage"><option value="register_page">Register Page</option><option value="otp">OTP</option></select></div>
        <div><label>Metric</label><select id="compare_metric"><option value="cost">Cost</option><option value="transition">Transition</option></select></div>
        <div><label>Sort</label><select id="compare_sort"><option value="lowest_cost">Lowest Cost</option><option value="highest_score">Highest Score</option></select></div>
        <div><label>&nbsp;</label><button onclick="loadComparison()">Run comparison</button></div>
      </div>
      <div class="table-wrap"><table><thead><tr><th>Rank</th><th>Type</th><th>Name</th><th>Value</th><th>Cost</th><th>Transition</th><th>Score</th></tr></thead><tbody id="comparisonRows"></tbody></table></div>
    </div>
    <div class="panel wide"><h2>Debug</h2><pre id="debug" class="debug"></pre></div>
  </section>
</div>
<script>
let definition = {definition_json};
let selectedStage = "register_page";
let latestFunnel = null;
const chart = id => echarts.init(document.getElementById(id));
const charts = {{}};
function filters() {{
  return {{
    date_from: document.getElementById("date_from").value,
    date_to: document.getElementById("date_to").value,
    campaign_id: document.getElementById("campaign_id").value || "all",
    adset_id: document.getElementById("adset_id").value || "all",
    device: document.getElementById("device").value || "all",
    placement: document.getElementById("placement").value || "all",
  }};
}}
async function api(url, options={{}}) {{
  const res = await fetch(url, options);
  if (!res.ok) throw new Error(await res.text());
  return await res.json();
}}
function setLoading(v) {{ document.getElementById("app").classList.toggle("loading", v); }}
function setError(msg) {{ document.getElementById("errorBox").innerHTML = msg ? `<div class="panel error">${{msg}}</div>` : ""; }}
function fillSelect(id, rows) {{
  const el = document.getElementById(id);
  el.innerHTML = rows.map(r => `<option value="${{r.id}}">${{r.name}}</option>`).join("");
}}
async function loadFilters() {{
  const data = await api("/api/journey/filters");
  fillSelect("campaign_id", data.campaigns);
  fillSelect("adset_id", data.adsets);
  fillSelect("device", data.devices);
  fillSelect("placement", data.placements);
}}
async function loadDefinition() {{
  definition = await api("/api/dashboard-definitions/customer_journey");
}}
function sourceBadge(source) {{ return `<span class="src">source: ${{source}}</span>`; }}
function renderKpis(stages) {{
  const picks = ["unique_ctr","unique_link_clicks","register_page","otp"];
  document.getElementById("kpis").innerHTML = picks.map(id => {{
    const s = stages.find(x => x.id === id) || {{}};
    return `<div class="panel kpi"><div class="muted">${{s.label || id}}</div><div class="v">${{s.value ?? "-"}}</div>${{sourceBadge(s.source || "-")}}</div>`;
  }}).join("");
}}
function renderStageRows(stages) {{
  document.getElementById("stageRows").innerHTML = stages.map(s => `<div class="stage-row" onclick="selectStage('${{s.id}}')"><strong>${{s.label}}</strong><span>${{s.value}}</span><span>${{s.transition_label}}</span><span class="pill ${{s.status}}">${{s.source}}</span></div>`).join("");
}}
function renderPath(stages) {{
  charts.path = charts.path || chart("pathChart");
  charts.path.setOption({{
    tooltip: {{ trigger: "axis" }},
    xAxis: {{ type:"category", data: stages.map(s=>s.label), axisLabel: {{ rotate: 25 }} }},
    yAxis: {{ type:"value" }},
    series: [{{ type:"bar", data: stages.map(s=>s.numeric_value), itemStyle: {{ color:"#2563eb" }} }}]
  }});
  charts.path.off("click");
  charts.path.on("click", p => selectStage(stages[p.dataIndex].id));
}}
function renderDrop(stages) {{
  charts.drop = charts.drop || chart("dropChart");
  charts.drop.setOption({{ tooltip:{{}}, xAxis:{{type:"category",data:stages.map(s=>s.label)}}, yAxis:{{type:"value"}}, series:[{{type:"bar",data:stages.map(s=>Math.round((s.drop_rate||0)*100)),itemStyle:{{color:"#dc2626"}}}}] }});
}}
function renderCost(stages) {{
  charts.cost = charts.cost || chart("costChart");
  charts.cost.setOption({{ tooltip:{{}}, xAxis:{{type:"category",data:stages.map(s=>s.label)}}, yAxis:{{type:"value"}}, series:[{{type:"line",smooth:true,data:stages.map(s=>s.cost||0),itemStyle:{{color:"#d97706"}}}}] }});
}}
async function selectStage(stageId) {{
  selectedStage = stageId;
  const data = await api(`/api/journey/stage-detail?stage_id=${{encodeURIComponent(stageId)}}&` + new URLSearchParams(filters()));
  document.getElementById("stageInspector").innerHTML = data.metrics.map(m => `<div class="metric"><strong>${{m.label}}</strong><div class="v">${{m.value}}</div>${{sourceBadge(m.source)}}</div>`).join("");
}}
async function loadFunnel() {{
  const data = await api("/api/dashboard-runtime/query", {{
    method:"POST",
    headers:{{"Content-Type":"application/json"}},
    body:JSON.stringify({{dashboard_id:definition.dashboard_id || "customer_journey", query_id:"journey_funnel", filters:filters()}})
  }});
  latestFunnel = data;
  renderKpis(data.stages); renderStageRows(data.stages); renderPath(data.stages); renderDrop(data.stages); renderCost(data.stages);
  await selectStage(selectedStage);
  document.getElementById("debug").textContent = JSON.stringify({{definition, debug:data.debug}}, null, 2);
}}
async function loadTrend() {{
  const qs = new URLSearchParams({{...filters(), stage_id:document.getElementById("trend_stage").value, metric:document.getElementById("trend_metric").value}});
  const data = await api("/api/journey/trend?" + qs);
  charts.trend = charts.trend || chart("trendChart");
  const series = data.series[0] || {{points:[]}};
  charts.trend.setOption({{ tooltip:{{trigger:"axis"}}, xAxis:{{type:"category",data:series.points.map(p=>p.date)}}, yAxis:{{type:"value"}}, series:[{{type:"line",smooth:true,data:series.points.map(p=>p.value)}}] }});
}}
async function loadComparison() {{
  const data = await api("/api/journey/comparison", {{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{stage_id:document.getElementById("compare_stage").value,metric:document.getElementById("compare_metric").value,sort:document.getElementById("compare_sort").value}})}});
  document.getElementById("comparisonRows").innerHTML = data.rows.map(r => `<tr><td>${{r.rank}}</td><td>${{r.entity_type}}</td><td>${{r.entity_name}}</td><td>${{r.stage_value}}</td><td>${{r.cost_per_stage}}</td><td>${{Math.round(r.transition_rate*1000)/10}}%</td><td>${{r.strength_score}}</td></tr>`).join("");
}}
async function reloadAll() {{
  setLoading(true); setError("");
  try {{ await loadFunnel(); await loadTrend(); await loadComparison(); }}
  catch(e) {{ setError(e.message); }}
  finally {{ setLoading(false); }}
}}
function toggleDebug() {{
  const el = document.getElementById("debug");
  el.style.display = el.style.display === "block" ? "none" : "block";
}}
["campaign_id","adset_id","device","placement","date_from","date_to"].forEach(id => document.addEventListener("change", e => {{ if(e.target.id === id) reloadAll(); }}));
["trend_stage","trend_metric","trend_from","trend_to"].forEach(id => document.addEventListener("change", e => {{ if(e.target.id === id) loadTrend(); }}));
loadDefinition().then(loadFilters).then(reloadAll);
</script>
</body>
</html>""")


@router.get("/dashboards/custom/{dashboard_id}", response_class=HTMLResponse)
async def custom_dashboard_page(dashboard_id: str):
    definition = _DEFINITIONS.get(dashboard_id)
    if not definition:
        raise HTTPException(status_code=404, detail="Dashboard definition was not found.")
    return HTMLResponse(_custom_dashboard_html(definition))


def _custom_dashboard_html(definition: dict) -> str:
    definition_json = dumps(definition, ensure_ascii=False)
    title = str(definition.get("title") or definition.get("dashboard_id") or "Custom Dashboard")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{title}</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
:root {{ --bg:#f5f7fb; --panel:#fff; --line:#dfe5ef; --text:#111827; --muted:#667085; --blue:#2563eb; --red:#dc2626; --green:#16a34a; --amber:#d97706; }}
body {{ margin:0; font-family:Arial, sans-serif; background:var(--bg); color:var(--text); }}
.shell {{ max-width:1480px; margin:0 auto; padding:22px; }}
.top {{ background:#111827; color:#fff; border-radius:12px; padding:20px; display:flex; justify-content:space-between; gap:18px; align-items:flex-start; }}
h1 {{ margin:0 0 8px; font-size:26px; }}
h2,h3 {{ margin:0 0 12px; }}
.muted {{ color:var(--muted); }} .top .muted {{ color:#cbd5e1; }}
.filters {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:12px; margin:16px 0; }}
.grid {{ display:grid; grid-template-columns:repeat(12,minmax(0,1fr)); gap:14px; align-items:start; }}
.panel {{ background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:16px; box-shadow:0 8px 22px rgba(15,23,42,.05); min-width:0; overflow:hidden; }}
.span-3 {{ grid-column:span 3; }} .span-4 {{ grid-column:span 4; }} .span-6 {{ grid-column:span 6; }} .span-8 {{ grid-column:span 8; }} .span-12 {{ grid-column:1 / -1; }}
label {{ display:block; color:var(--muted); font-size:12px; margin-bottom:6px; }}
input,select {{ width:100%; box-sizing:border-box; border:1px solid #cfd7e6; border-radius:8px; padding:10px; background:white; }}
button {{ border:0; border-radius:9px; background:var(--blue); color:white; padding:11px 14px; font-weight:700; cursor:pointer; }}
button.secondary {{ background:#475467; }}
button:disabled {{ opacity:.65; cursor:wait; }}
.value {{ font-size:28px; font-weight:800; margin-top:8px; }}
.chart {{ width:100%; height:330px; }}
.table-wrap {{ overflow-x:auto; border:1px solid #edf0f5; border-radius:10px; }}
table {{ width:100%; min-width:720px; border-collapse:collapse; font-size:14px; }}
th,td {{ border-bottom:1px solid #edf0f5; padding:10px; text-align:left; vertical-align:top; overflow-wrap:anywhere; }}
th {{ background:#f8fafc; color:#475467; }}
.bar {{ height:10px; background:#2563eb; border-radius:999px; min-width:4px; }}
.src {{ color:var(--muted); font-size:12px; margin-top:4px; }}
.empty {{ padding:14px; border:1px dashed #cbd5e1; border-radius:10px; color:#667085; background:#f8fafc; }}
.debug {{ white-space:pre-wrap; background:#0f172a; color:#dbeafe; border-radius:10px; padding:12px; font-size:12px; display:none; }}
.error {{ border-color:#fecaca; background:#fff1f2; color:#991b1b; margin-bottom:12px; }}
@media(max-width:920px) {{ .span-3,.span-4,.span-6,.span-8 {{ grid-column:1 / -1; }} }}
</style>
</head>
<body>
<div class="shell" id="app">
  <section class="top">
    <div><h1 id="title"></h1><div id="subtitle" class="muted"></div></div>
    <div><button id="refreshBtn" onclick="reloadDashboard()">Refresh</button> <button class="secondary" onclick="toggleDebug()">Debug</button></div>
  </section>
  <section id="filters" class="filters"></section>
  <section id="errorBox"></section>
  <section id="widgets" class="grid"></section>
  <section class="panel span-12" style="margin-top:14px"><h3>Debug</h3><pre id="debug" class="debug"></pre></section>
</div>
<script>
let definition = {definition_json};
let latestData = null;
const charts = {{}};
function api(url, options={{}}) {{ return fetch(url, options).then(async r => {{ if(!r.ok) throw new Error(await r.text()); return r.json(); }}); }}
function filterValue(key) {{ const el = document.getElementById("filter_" + key); return el ? el.value : "all"; }}
function filters() {{
  const out = {{}};
  (definition.filters || []).forEach(f => out[f.key] = filterValue(f.key));
  ["date_from","date_to","campaign_id","adset_id","ad_id","device","placement"].forEach(k => {{ if(out[k] === undefined) out[k] = k.includes("_id") || ["device","placement"].includes(k) ? "all" : ""; }});
  return out;
}}
function spanClass(widget) {{ const span = Number(widget.span || widget.width || (widget.type === "kpi" ? 3 : 6)); return "span-" + ([3,4,6,8,12].includes(span) ? span : 6); }}
function renderFilters() {{
  document.getElementById("filters").innerHTML = (definition.filters || []).map(f => {{
    const key = f.key; const label = f.label || key; const type = f.type || "text";
    if(type === "date" || key === "date_from" || key === "date_to") return `<div class="panel"><label>${{label}}</label><input id="filter_${{key}}" type="date" value="${{f.default || ""}}"></div>`;
    const opts = (f.options || [{{id:"all",name:"All"}}]).map(o => `<option value="${{o.id ?? o.value}}">${{o.name ?? o.label ?? o.value}}</option>`).join("");
    if(type === "select" || key.endsWith("_id") || key === "device" || key === "placement") return `<div class="panel"><label>${{label}}</label><select id="filter_${{key}}">${{opts}}</select></div>`;
    return `<div class="panel"><label>${{label}}</label><input id="filter_${{key}}" value="${{f.default || ""}}"></div>`;
  }}).join("");
  document.querySelectorAll("#filters input,#filters select").forEach(el => el.addEventListener("change", reloadDashboard));
}}
function stageRows() {{ return (latestData && latestData.stages) || []; }}
function widgetRows(widget) {{
  if(widget.stages) return stageRows().filter(s => widget.stages.includes(s.id));
  if(widget.source === "stages" || widget.data_query === "journey_funnel") return stageRows();
  return [];
}}
function tableHtml(rows) {{
  if(!rows.length) return '<div class="empty">No data available.</div>';
  const cols = Object.keys(rows[0] || {{}}).filter(c => !["metric_source","warnings"].includes(c));
  return `<div class="table-wrap"><table><thead><tr>${{cols.map(c=>`<th>${{c}}</th>`).join("")}}</tr></thead><tbody>${{rows.map(r=>`<tr>${{cols.map(c=>`<td>${{typeof r[c] === "object" ? JSON.stringify(r[c]) : (r[c] ?? "")}}</td>`).join("")}}</tr>`).join("")}}</tbody></table></div>`;
}}
function renderWidget(widget) {{
  const rows = widgetRows(widget);
  const type = widget.type || "table";
  const title = widget.title || widget.id || type;
  if(type === "kpi") {{
    const stage = rows.find(s => s.id === widget.stage || s.id === widget.metric || s.id === widget.metric_id) || rows[0] || {{}};
    return `<div class="panel ${{spanClass(widget)}}"><div class="muted">${{title}}</div><div class="value">${{stage.value ?? stage.numeric_value ?? "-"}}</div><div class="src">${{stage.source || ""}}</div></div>`;
  }}
  if(["conversion_path","funnel","bar","line"].includes(type)) {{
    return `<div class="panel ${{spanClass(widget)}}"><h3>${{title}}</h3><div id="chart_${{widget.id}}" class="chart"></div></div>`;
  }}
  if(type === "text") return `<div class="panel ${{spanClass(widget)}}"><h3>${{title}}</h3><p>${{widget.text || widget.config?.text || ""}}</p></div>`;
  return `<div class="panel ${{spanClass(widget)}}"><h3>${{title}}</h3>${{tableHtml(rows)}}</div>`;
}}
function drawCharts() {{
  (definition.widgets || []).forEach(widget => {{
    if(!["conversion_path","funnel","bar","line"].includes(widget.type)) return;
    const el = document.getElementById("chart_" + widget.id); if(!el) return;
    const chart = charts[widget.id] || echarts.init(el); charts[widget.id] = chart;
    const rows = widgetRows(widget);
    chart.setOption({{
      tooltip:{{trigger:"axis"}},
      xAxis:{{type:"category",data:rows.map(r=>r.label || r.id), axisLabel:{{rotate:25}}}},
      yAxis:{{type:"value"}},
      series:[{{type: widget.type === "line" ? "line" : "bar", smooth:true, data:rows.map(r=>r.numeric_value || 0), itemStyle:{{color:"#2563eb"}}}}]
    }});
  }});
}}
function render() {{
  document.getElementById("title").textContent = definition.title || definition.dashboard_id || "Custom Dashboard";
  document.getElementById("subtitle").textContent = definition.description || "Manifest-driven dashboard";
  const widgets = definition.widgets && definition.widgets.length ? definition.widgets : [{{id:"conversion_path",type:"conversion_path",title:"Conversion Path",span:12,stages:(definition.stages||[]).map(s=>s.id)}},{{id:"stage_table",type:"table",title:"Stage Data",span:12,source:"stages"}}];
  definition.widgets = widgets;
  document.getElementById("widgets").innerHTML = widgets.map(renderWidget).join("");
  drawCharts();
  document.getElementById("debug").textContent = JSON.stringify({{definition, runtime:latestData?.debug, filters:filters()}}, null, 2);
}}
async function reloadDashboard() {{
  document.getElementById("refreshBtn").disabled = true;
  document.getElementById("errorBox").innerHTML = "";
  try {{
    latestData = await api("/api/dashboard-runtime/query", {{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{dashboard_id:definition.dashboard_id, query_id:"journey_funnel", filters:filters()}})}});
    render();
  }} catch(e) {{
    document.getElementById("errorBox").innerHTML = `<div class="panel error">${{e.message}}</div>`;
  }} finally {{
    document.getElementById("refreshBtn").disabled = false;
  }}
}}
function toggleDebug() {{ const el = document.getElementById("debug"); el.style.display = el.style.display === "block" ? "none" : "block"; }}
renderFilters(); reloadDashboard();
</script>
</body>
</html>"""



def _save_dashboard_definition(definition: dict, dashboard_id: str | None = None) -> dict:
    resolved_dashboard_id = str(dashboard_id or definition.get("dashboard_id") or "custom_dashboard")
    definition["dashboard_id"] = resolved_dashboard_id
    _DEFINITIONS[resolved_dashboard_id] = definition
    return {"success": True, "definition": definition, "url": _dashboard_url(resolved_dashboard_id)}


@router.post("/api/dashboard-definitions", operation_id="create_dashboard_definition_manifest_v1")
async def create_dashboard_definition(body: DashboardDefinitionRequest):
    definition = body.model_dump()
    return _save_dashboard_definition(definition)


@router.post("/api/dashboard-definitions/v2", operation_id="create_dashboard_manifest_v2")
async def create_dashboard_definition_v2(body: DashboardDefinitionRequest):
    definition = body.model_dump()
    return _save_dashboard_definition(definition)


@router.get("/api/dashboard-definitions/{dashboard_id}")
async def get_dashboard_definition(dashboard_id: str):
    return _DEFINITIONS.get(dashboard_id, DEFAULT_DASHBOARD_DEFINITION)


@router.put("/api/dashboard-definitions/{dashboard_id}", operation_id="update_dashboard_definition_manifest_v1")
async def update_dashboard_definition(dashboard_id: str, body: DashboardDefinitionUpdateRequest):
    definition = body.model_dump()
    return _save_dashboard_definition(definition, dashboard_id=dashboard_id)


@router.put("/api/dashboard-definitions/v2/{dashboard_id}", operation_id="update_dashboard_manifest_v2")
async def update_dashboard_definition_v2(dashboard_id: str, body: DashboardDefinitionUpdateRequest):
    definition = body.model_dump()
    return _save_dashboard_definition(definition, dashboard_id=dashboard_id)


@router.post("/api/dashboard-runtime/query")
async def dashboard_runtime_query(body: DashboardRuntimeQueryRequest, request: Request):
    dashboard_id = str(body.dashboard_id or "customer_journey")
    query_id = str(body.query_id or "journey_funnel")
    filters = body.filters or {}
    definition = _DEFINITIONS.get(dashboard_id, DEFAULT_DASHBOARD_DEFINITION)
    if query_id == "journey_funnel":
        return await _live_or_fallback_funnel(request, filters, definition)
    if query_id == "journey_trend":
        return trend(filters=filters)
    if query_id == "journey_comparison":
        return comparison()
    return {"definition": definition, "query_plan": build_query_plan(definition, query_id), "filters": filters}


@router.get("/api/dashboard-runtime/connectors")
async def dashboard_connectors():
    return {"connectors": CONNECTOR_REGISTRY, "metrics": METRIC_DICTIONARY}


@router.get("/api/dashboard-runtime/events/discover")
async def discover_dashboard_events(
    request: Request,
    account_id: str | None = None,
    pixel_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    campaign_id: str | None = None,
    adset_id: str | None = None,
    ad_id: str | None = None,
):
    token = await resolve_access_token(request)
    clean_account_id = str(account_id or DEFAULT_DASHBOARD_DEFINITION["data_sources"]["meta"]["account_id"]).strip()
    if clean_account_id and not clean_account_id.startswith("act_"):
        clean_account_id = f"act_{clean_account_id}"
    filters = {
        "campaign_id": campaign_id or "all",
        "adset_id": adset_id or "all",
        "ad_id": ad_id or "all",
        "date_from": date_from,
        "date_to": date_to,
    }
    scope_id, entity_scope = _meta_scope_id(filters, {"data_sources": {"meta": {"account_id": clean_account_id}}})
    meta_payload = meta_call(
        "GET",
        f"{scope_id}/insights",
        token,
        params={"fields": "actions", "limit": 100, **_meta_date_params(filters)},
    )
    action_rows = []
    for row in meta_payload.get("data") or []:
        for item in row.get("actions") or []:
            action_type = str(item.get("action_type") or "")
            action_rows.append(
                {
                    "action_type": action_type,
                    "sample_value": _to_number(item.get("value")),
                    "source": "meta_actions",
                    "status": "unmapped" if action_type.casefold() == "offsite_conversion.fb_pixel_custom" else "available",
                }
            )
    custom_conversions = []
    try:
        custom_conversions = _meta_rows(
            f"{clean_account_id}/customconversions",
            token,
            {"fields": "id,name,event_source_type,custom_event_type,pixel{id,name}", "limit": 200},
        )
    except Exception:
        custom_conversions = []
    pixel_events = []
    if pixel_id:
        try:
            stats = meta_call(
                "GET",
                f"{pixel_id}/stats",
                token,
                params={"aggregation": "event_total_counts", "start_time": date_from, "end_time": date_to},
            )
            pixel_events = stats.get("data") or []
        except Exception:
            pixel_events = []
    return {
        "meta_actions": action_rows,
        "custom_conversions": custom_conversions,
        "pixel_events": pixel_events,
        "status": "needs_mapping" if any(item["status"] == "unmapped" for item in action_rows) else "ready",
        "debug": {
            "scope_id": scope_id,
            "entity_scope": entity_scope,
            "account_id": clean_account_id,
            "pixel_id": pixel_id,
            "filters_sent": filters,
        },
    }


async def _live_or_fallback_funnel(request: Request, filters: dict, definition: dict) -> dict:
    debug = {"connector_errors": [], "connector_status": {"meta": "not_attempted"}, "filters_sent": filters, "mode": "fallback_data"}
    token = None
    try:
        token = await resolve_access_token(request)
    except HTTPException as exc:
        debug["connector_errors"].append({"source": "meta", "stage": "auth", "error": exc.detail})
        debug["connector_status"]["meta"] = "auth_failed"
    if not token:
        return build_mixed_funnel(None, filters, debug=debug, definition=definition)

    try:
        meta_payload, meta_debug = _fetch_live_meta_funnel(filters, definition, token)
        debug.update(meta_debug)
        debug["mode"] = "live_data"
        debug["connector_status"]["meta"] = "success"
        return build_mixed_funnel(meta_payload, filters, debug=debug, definition=definition)
    except HTTPException as exc:
        debug["connector_errors"].append({"source": "meta", "stage": "insights", "error": exc.detail})
        debug["connector_status"]["meta"] = "failed"
    except Exception as exc:
        debug["connector_errors"].append({"source": "meta", "stage": "insights", "error": str(exc)})
        debug["connector_status"]["meta"] = "failed"
    return build_mixed_funnel(None, filters, debug=debug, definition=definition)


def _fetch_live_meta_funnel(filters: dict, definition: dict, token: str) -> tuple[dict, dict]:
    scope_id, entity_scope = _meta_scope_id(filters, definition)
    params = {
        "fields": META_DASHBOARD_FIELDS,
        "limit": 100,
        **_meta_date_params(filters),
    }
    path = f"{scope_id}/insights"
    payload = meta_call("GET", path, token, params=params)
    return payload, {
        "meta_path": path,
        "meta_params": params,
        "time_range": params.get("time_range"),
        "date_preset": params.get("date_preset"),
        "entity_scope": entity_scope,
    }


def _meta_scope_id(filters: dict, definition: dict) -> tuple[str, dict]:
    for key in ("ad_id", "adset_id", "campaign_id"):
        value = str(filters.get(key) or "").strip()
        if value and value.lower() != "all":
            return value, {"type": key.replace("_id", ""), "id": value}
    account_id = (
        (definition.get("data_sources") or {})
        .get("meta", {})
        .get("account_id", DEFAULT_DASHBOARD_DEFINITION["data_sources"]["meta"]["account_id"])
    )
    clean = str(account_id or "").strip()
    if clean and not clean.startswith("act_"):
        return f"act_{clean}", {"type": "account", "id": f"act_{clean}"}
    resolved = clean or DEFAULT_DASHBOARD_DEFINITION["data_sources"]["meta"]["account_id"]
    return resolved, {"type": "account", "id": resolved}


def _meta_date_params(filters: dict) -> dict:
    date_from = str(filters.get("date_from") or "").strip()
    date_to = str(filters.get("date_to") or "").strip()
    if date_from and date_to:
        return {"time_range": {"since": date_from, "until": date_to}}
    return {"date_preset": "last_7d"}


@router.get("/api/journey/filters")
async def journey_filters(request: Request):
    fallback = filter_options()
    try:
        token = await resolve_access_token(request)
        account_id = _first_ad_account_id(token)
        campaigns = _meta_rows(f"{account_id}/campaigns", token, {"fields": "id,name,status,effective_status", "limit": 100})
        adsets = _meta_rows(f"{account_id}/adsets", token, {"fields": "id,name,status,effective_status,campaign_id", "limit": 100})
        return {
            **fallback,
            "campaigns": [{"id": "all", "name": "All"}] + [{"id": item.get("id"), "name": item.get("name") or item.get("id")} for item in campaigns],
            "adsets": [{"id": "all", "name": "All"}] + [{"id": item.get("id"), "name": item.get("name") or item.get("id")} for item in adsets],
            "debug": {"mode": "live_data", "meta_account_id": account_id},
        }
    except Exception as exc:
        fallback["debug"] = {"mode": "fallback_options", "error": str(getattr(exc, "detail", exc))}
        return fallback


def _first_ad_account_id(token: str) -> str:
    rows = _meta_rows("me/adaccounts", token, {"fields": "id,name,account_id", "limit": 50})
    if not rows:
        return DEFAULT_DASHBOARD_DEFINITION["data_sources"]["meta"]["account_id"]
    account_id = str(rows[0].get("id") or rows[0].get("account_id") or "").strip()
    if account_id and not account_id.startswith("act_"):
        return f"act_{account_id}"
    return account_id or DEFAULT_DASHBOARD_DEFINITION["data_sources"]["meta"]["account_id"]


def _meta_rows(path: str, token: str, params: dict) -> list[dict]:
    payload = meta_call("GET", path, token, params=params)
    return payload.get("data") or []


def _to_number(value) -> float:
    try:
        return float(str(value or 0).replace(",", ""))
    except ValueError:
        return 0.0


@router.get("/api/journey/funnel")
async def journey_funnel(
    request: Request,
    date_from: str | None = None,
    date_to: str | None = None,
    campaign_id: str = "all",
    adset_id: str = "all",
    ad_id: str = "all",
    device: str = "all",
    placement: str = "all",
):
    filters = {
        "date_from": date_from,
        "date_to": date_to,
        "campaign_id": campaign_id,
        "adset_id": adset_id,
        "ad_id": ad_id,
        "device": device,
        "placement": placement,
    }
    return await _live_or_fallback_funnel(request, filters, DEFAULT_DASHBOARD_DEFINITION)


@router.get("/api/journey/stage-detail")
async def journey_stage_detail(stage_id: str = Query(...), date_from: str | None = None, date_to: str | None = None, campaign_id: str = "all", adset_id: str = "all", ad_id: str = "all", device: str = "all"):
    return stage_detail(stage_id, locals())


@router.get("/api/journey/trend")
async def journey_trend(stage_id: str = "register_page", metric: str = "value", granularity: str = "daily", level: str = "campaign", campaign_id: str = "all"):
    return trend(stage_id=stage_id, metric=metric, filters={"campaign_id": campaign_id, "granularity": granularity, "level": level})


@router.post("/api/journey/comparison")
async def journey_comparison(body: JourneyComparisonRequest):
    return comparison(
        entities=[entity.model_dump() for entity in body.entities] or None,
        stage_id=body.stage_id,
        metric=body.metric,
        sort=body.sort,
    )
