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
from app.analytics.clarity_metrics import normalize_clarity_export, summarize_clarity_metrics
from app.analytics.ga4_preprocessing import normalize_ga4_report
from app.core.auth import resolve_access_token
from app.core.clarity_client import run_clarity_live_insights_with_fallbacks
from app.core.ga4_client import run_ga4_report
from app.core.meta_client import meta_call
from app.core.oauth_store import create_dynamic_dashboard, get_dynamic_dashboard, update_dynamic_dashboard_config
from app.core.dashboard_runtime import execute_plan as execute_universal_dashboard_plan
from app.core.dashboard_plan import compile_runtime_query
from app.core.dashboard_store import DashboardStore

router = APIRouter(tags=["journey-dashboard-v7"])

_DEFINITIONS = {DEFAULT_DASHBOARD_DEFINITION["dashboard_id"]: DEFAULT_DASHBOARD_DEFINITION}
_CODE_DASHBOARDS: dict[str, dict[str, Any]] = {}
META_DASHBOARD_FIELDS = (
    "campaign_id,campaign_name,spend,impressions,reach,clicks,inline_link_clicks,"
    "unique_inline_link_clicks,unique_ctr,actions,action_values,purchase_roas,date_start,date_stop"
)


def _dashboard_store() -> DashboardStore:
    return DashboardStore(
        definitions=_DEFINITIONS,
        code_dashboards=_CODE_DASHBOARDS,
        create_dashboard=create_dynamic_dashboard,
        get_dashboard=get_dynamic_dashboard,
        update_dashboard=update_dynamic_dashboard_config,
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


class DashboardCodeRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    dashboard_id: str = Field("custom_code_dashboard", description="Stable dashboard id.")
    title: str | None = Field(None, description="Dashboard title.")
    description: str | None = Field(None, description="Optional dashboard description.")
    html: str = Field(..., description="Body HTML for a full custom dashboard.")
    css: str = Field("", description="Dashboard CSS.")
    javascript: str = Field("", description="Dashboard JavaScript.")
    data_contract: dict[str, Any] = Field(default_factory=dict, description="Runtime query and data expectations.")


class DashboardCodeUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    title: str | None = Field(None, description="Dashboard title.")
    description: str | None = Field(None, description="Optional dashboard description.")
    html: str = Field(..., description="Body HTML for a full custom dashboard.")
    css: str = Field("", description="Dashboard CSS.")
    javascript: str = Field("", description="Dashboard JavaScript.")
    data_contract: dict[str, Any] = Field(default_factory=dict, description="Runtime query and data expectations.")


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


def _code_dashboard_url(dashboard_id: str) -> str:
    path = f"/dashboards/code/{dashboard_id}"
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
    definition = _get_dashboard_definition(dashboard_id)
    if not definition:
        raise HTTPException(status_code=404, detail="Dashboard definition was not found.")
    return HTMLResponse(_custom_dashboard_html(definition))


@router.get("/dashboards/code/{dashboard_id}", response_class=HTMLResponse)
async def code_dashboard_page(dashboard_id: str):
    dashboard = _get_code_dashboard(dashboard_id)
    if not dashboard:
        raise HTTPException(status_code=404, detail="Code dashboard was not found.")
    return HTMLResponse(_code_dashboard_html(dashboard))


def _code_dashboard_html(dashboard: dict[str, Any]) -> str:
    dashboard_json = dumps(
        {
            "dashboard_id": dashboard.get("dashboard_id"),
            "title": dashboard.get("title"),
            "description": dashboard.get("description"),
            "data_contract": dashboard.get("data_contract") or {},
        },
        ensure_ascii=False,
    )
    title = str(dashboard.get("title") or dashboard.get("dashboard_id") or "Code Dashboard")
    html = str(dashboard.get("html") or "")
    css = str(dashboard.get("css") or "")
    javascript = str(dashboard.get("javascript") or "")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{title}</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
* {{ box-sizing:border-box; }}
body {{ margin:0; font-family:Arial, sans-serif; background:#f5f7fb; color:#111827; }}
button {{ cursor:pointer; }}
{css}
</style>
</head>
<body>
{html}
<script>
window.ALLINGPT_DASHBOARD = {dashboard_json};
window.ALLINGPT = {{
  dashboard: window.ALLINGPT_DASHBOARD,
  async runQuery(queryId, filters = {{}}, context = {{}}) {{
    const res = await fetch("/api/dashboard-runtime/query", {{
      method: "POST",
      headers: {{"Content-Type":"application/json"}},
      body: JSON.stringify({{
        dashboard_id: window.ALLINGPT_DASHBOARD.dashboard_id,
        query_id: queryId || "journey_funnel",
        filters,
        context: {{...context, data_contract: window.ALLINGPT_DASHBOARD.data_contract || {{}}}}
      }})
    }});
    if (!res.ok) throw new Error(await res.text());
    return await res.json();
  }},
  async getDefinition() {{
    const res = await fetch("/api/dashboard-code/v1/" + encodeURIComponent(window.ALLINGPT_DASHBOARD.dashboard_id));
    if (!res.ok) throw new Error(await res.text());
    return await res.json();
  }}
}};
{javascript}
</script>
</body>
</html>"""


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
.funnel-flow {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:14px; align-items:stretch; }}
.funnel-stage {{ position:relative; min-height:210px; border:1px solid #dbe4f0; border-top:4px solid var(--blue); border-radius:12px; padding:15px; background:linear-gradient(180deg,#fff,#f8fafc); }}
.funnel-stage.missing {{ border-top-color:var(--amber); background:#fffbeb; }}
.funnel-stage::after {{ content:"→"; position:absolute; right:-13px; top:45%; width:24px; height:24px; display:grid; place-items:center; border-radius:50%; background:#e8eef8; color:#475467; font-weight:800; z-index:2; }}
.funnel-stage:last-child::after {{ display:none; }}
.stage-head {{ display:flex; justify-content:space-between; gap:8px; align-items:flex-start; }}
.stage-name {{ font-weight:800; line-height:1.25; }}
.source-badge {{ border-radius:999px; padding:4px 8px; font-size:11px; background:#eef4ff; color:#1d4ed8; white-space:nowrap; }}
.stage-number {{ font-size:30px; font-weight:900; margin:18px 0 12px; letter-spacing:-.02em; }}
.stage-metrics {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; font-size:12px; }}
.stage-metric {{ background:#f1f5f9; border-radius:8px; padding:8px; }}
.stage-metric b {{ display:block; color:#344054; margin-top:3px; font-size:13px; }}
.stage-details {{ margin-top:10px; padding-top:9px; border-top:1px dashed #cbd5e1; font-size:12px; color:#475467; }}
.section-state {{ margin:0 0 14px; padding:10px 12px; border-radius:9px; background:#f8fafc; color:#475467; border:1px solid #e2e8f0; }}
.section-state.error {{ background:#fff1f2; color:#b42318; border-color:#fecdd3; }}
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
let latestDataByQuery = {{}};
let queryErrors = {{}};
let runtimeFilterOptions = {{}};
let hasLoadedDashboard = false;
const charts = {{}};
function api(url, options={{}}) {{ return fetch(url, options).then(async r => {{ if(!r.ok) throw new Error(await r.text()); return r.json(); }}); }}
function filterValue(key) {{ const el = document.getElementById("filter_" + key); return el ? el.value : ""; }}
function effectiveFilters() {{
  const byKey = new Map((definition.filters || []).filter(item => item && item.key).map(item => [item.key, item]));
  byKey.delete("date_range");
  const required = [
    {{key:"date_from", label:"Start date", type:"date"}},
    {{key:"date_to", label:"End date", type:"date"}},
    {{key:"account_id", label:"Ad account", type:"select"}},
    {{key:"campaign_id", label:"Campaign", type:"select"}},
    {{key:"adset_id", label:"Ad Set", type:"select"}},
    {{key:"ad_id", label:"Ad", type:"select"}}
  ];
  const ordered = required.map(item => byKey.get(item.key) || item);
  const standard = new Set(required.map(item => item.key));
  return [...ordered, ...[...byKey.values()].filter(item => !standard.has(item.key))];
}}
function filters() {{
  const out = {{}};
  effectiveFilters().forEach(f => out[f.key] = filterValue(f.key));
  ["date_from","date_to","campaign_id","adset_id","ad_id","device","placement"].forEach(k => {{ if(out[k] === undefined) out[k] = k.includes("_id") || ["device","placement"].includes(k) ? "all" : ""; }});
  const selected = key => String(out[key] || "").trim() && String(out[key]).toLowerCase() !== "all" ? out[key] : "";
  const ga4ScopeValues = key => {{
    const value = selected(key);
    const element = document.getElementById("filter_" + key);
    const label = value && element && element.selectedIndex >= 0 ? String(element.options[element.selectedIndex].text || "").trim() : "";
    const plusEncoded = label ? encodeURIComponent(label).replace(/%20/g, "+") : "";
    return [...new Set([value, label, plusEncoded].filter(Boolean))];
  }};
  const adId = selected("ad_id"), adsetId = selected("adset_id"), campaignId = selected("campaign_id"), accountId = selected("account_id");
  out.scope_id = adId || adsetId || campaignId || accountId || "";
  out.analysis_level = adId ? "ad" : adsetId ? "adset" : "campaign";
  out.campaign_ga4_values = ga4ScopeValues("campaign_id");
  out.adset_ga4_values = ga4ScopeValues("adset_id");
  out.ad_ga4_values = ga4ScopeValues("ad_id");
  out.since = out.date_from || "";
  out.until = out.date_to || "";
  out.date_range = {{start_date:out.since,end_date:out.until}};
  const configuredPreset = (definition.filters || []).find(item => item.key === "date_preset")?.default;
  const selectedPreset = selected("date_preset") || configuredPreset || "last_30d";
  out.date_preset = out.since && out.until ? "custom" : selectedPreset;
  return out;
}}
function spanClass(widget) {{ const span = Number(widget.span || widget.width || (widget.type === "kpi" ? 3 : 6)); return "span-" + ([3,4,6,8,12].includes(span) ? span : 6); }}
function optionRows(value) {{
  if(Array.isArray(value)) return value;
  if(value && Array.isArray(value.data)) return value.data;
  if(value && Array.isArray(value.options)) return value.options;
  return [];
}}
function optionFor(row) {{
  if(!row || typeof row !== "object") return null;
  const value = row.value ?? row.id ?? row.account_id;
  if(value === undefined || value === null || value === "") return null;
  return {{value:String(value), label:String(row.label ?? row.name ?? row.account_name ?? value)}};
}}
function queryIdForWidget(widget) {{
  if(widget.data_query) return widget.data_query;
  if(definition.runtime_queries && definition.runtime_queries[widget.id]) return widget.id;
  if(widget.source && definition.runtime_queries && definition.runtime_queries[widget.source]) return widget.source;
  if(widget.config?.query && definition.runtime_queries && definition.runtime_queries[widget.config.query]) return widget.config.query;
  if(widget.config?.metrics?.length && definition.runtime_queries?.meta_insights && ["table","kpi","bar","line"].includes(widget.type)) return "meta_insights";
  return "journey_funnel";
}}
function filterDependencies(filter) {{
  const raw = filter && filter.depends_on;
  if(Array.isArray(raw)) return raw.filter(Boolean);
  return raw ? [raw] : [];
}}
function queryIdForFilter(filter) {{
  const source = (filter && filter.options_source) || {{}};
  const defaults = {{account_id:"accounts",campaign_id:"campaigns",adset_id:"adsets",ad_id:"ads"}};
  const candidates = [source.runtime_query, source.query_id, source.resource, defaults[filter && filter.key]].filter(Boolean);
  return candidates.find(id => definition.runtime_queries && definition.runtime_queries[id]) || "";
}}
function filterSelectionReady(filter, selected) {{
  return filterDependencies(filter).every(key => {{
    const value = String(selected[key] || "").trim().toLowerCase();
    return value && value !== "all";
  }});
}}
function isControlWidget(widget) {{
  if(["filters","filter_control"].includes(widget.type)) return true;
  const plan = definition.runtime_queries && definition.runtime_queries[queryIdForWidget(widget)];
  return Boolean(plan && (plan.nodes || []).some(node => node.connector === "meta" && node.operation === "list_accounts"));
}}
function findNodeOptions(result, keys) {{
  const nodes = (result && result.nodes) || {{}};
  const data = (result && result.data) || {{}};
  for(const key of keys) {{
    const rows = optionRows(data[key]);
    if(rows.length) return rows.map(optionFor).filter(Boolean);
    const nodeRows = optionRows(nodes[key]);
    if(nodeRows.length) return nodeRows.map(optionFor).filter(Boolean);
  }}
  return [];
}}
function updateRuntimeFilterOptions(result) {{
  if(!result) return false;
  const mappings = {{
    account_id:["account_options","accounts","get_accounts"],
    campaign_id:["campaign_options","campaigns","get_campaigns"],
    adset_id:["adset_options","adsets","get_adsets"],
    ad_id:["ad_options","ads","get_ads"]
  }};
  let changed = false;
  Object.entries(mappings).forEach(([key, nodeKeys]) => {{
    const next = findNodeOptions(result, nodeKeys);
    if(next.length) {{ runtimeFilterOptions[key] = next; changed = true; }}
  }});
  return changed;
}}
function cascadeKeys(key) {{
  const order = ["account_id","campaign_id","adset_id","ad_id"];
  const index = order.indexOf(key);
  return index < 0 ? [] : order.slice(index + 1);
}}
function renderFilters() {{
  const configuredFilters = effectiveFilters();
  const selected = Object.fromEntries(configuredFilters.map(f => [f.key, filterValue(f.key)]));
  document.getElementById("filters").innerHTML = configuredFilters.map(f => {{
    const key = f.key; const label = f.label || key; const type = f.type || "text";
    const value = selected[key] || f.default || "";
    if(type === "date" || key === "date_from" || key === "date_to") return `<div class="panel"><label>${{label}}</label><input id="filter_${{key}}" type="date" value="${{value}}"></div>`;
    const options = runtimeFilterOptions[key] || f.options || [];
    const opts = [{{value:"all",label:"All"}}, ...options.map(optionFor).filter(Boolean)].map(o => `<option value="${{o.value}}" ${{String(o.value) === String(value) ? "selected" : ""}}>${{o.label}}</option>`).join("");
    if(type === "select" || key.endsWith("_id") || key === "device" || key === "placement") return `<div class="panel"><label>${{label}}</label><select id="filter_${{key}}" ${{filterSelectionReady(f, selected) ? "" : "disabled"}}>${{opts}}</select></div>`;
    return `<div class="panel"><label>${{label}}</label><input id="filter_${{key}}" value="${{value}}"></div>`;
  }}).join("");
  document.querySelectorAll("#filters input,#filters select").forEach(el => el.addEventListener("change", event => {{
    cascadeKeys(event.target.id.replace("filter_", "")).forEach(key => {{
      const child = document.getElementById("filter_" + key);
      if(child) child.value = "all";
      delete runtimeFilterOptions[key];
    }});
    reloadDashboard();
  }}));
}}
function resultPayload(result) {{ return result && result.data !== undefined ? result.data : (result || {{}}); }}
function stageRows(result=latestData) {{
  const payload = resultPayload(result);
  if(Array.isArray(payload?.stages)) return payload.stages;
  if(Array.isArray(payload)) return payload;
  for(const value of Object.values(payload || {{}})) if(Array.isArray(value) && value.some(row => row && (row.id || row.stage || row.label))) return value;
  return [];
}}
function metricFromRow(row, metric) {{
  if(row && row[metric] !== undefined) return row[metric];
  const aliases = {{landing_page_views:"landing_page_view"}};
  const actionType = aliases[metric] || metric;
  const collection = metric.startsWith("cost_per_") ? row?.cost_per_action_type : row?.actions;
  const target = metric.startsWith("cost_per_") ? metric.slice("cost_per_".length) : actionType;
  const match = (collection || []).find(item => item && item.action_type === target);
  return match?.value ?? null;
}}
function configuredMetricRows(widget, rows) {{
  const dimensions = widget.dimensions?.length ? widget.dimensions : (widget.config?.dimensions || []);
  const metrics = widget.config?.metrics || [];
  if(!metrics.length) return rows;
  return rows.map(row => Object.fromEntries(
    [...dimensions, ...metrics].map(key => [key, dimensions.includes(key) ? (row[key] ?? row.name ?? row.ad_name ?? row.adset_name ?? row.campaign_name ?? "") : metricFromRow(row, key)])
  ));
}}
function widgetRows(widget) {{
  const result = latestDataByQuery[queryIdForWidget(widget)] || latestData;
  const payload = resultPayload(result);
  if(widget.stages) {{
    const stageIds = widget.stages.map(stage => typeof stage === "string" ? stage : stage?.id).filter(Boolean);
    return stageRows(result).filter(s => stageIds.includes(s.id));
  }}
  if(widget.source && Array.isArray(payload?.[widget.source])) return payload[widget.source];
  if(widget.source === "stages" || widget.data_query === "journey_funnel" || widget.type === "funnel") return stageRows(result);
  if(["comparison","tracking_gap"].includes(widget.type) && Array.isArray(payload?.stages)) return payload.stages;
  if(Array.isArray(payload)) return payload;
  const containers = [payload, ...Object.values(payload || {{}}), ...Object.values(result?.nodes || {{}})];
  for(const value of containers) {{
    const rows = optionRows(value);
    if(rows.length) return configuredMetricRows(widget, rows);
  }}
  return payload && Object.keys(payload).length ? [payload] : [];
}}
function emptyStateMessage(widget) {{
  const result = latestDataByQuery[queryIdForWidget(widget)] || latestData;
  const waiting = (result && result.node_status || []).find(item => item.status === "waiting_for_input");
  if(waiting && waiting.missing_inputs?.length) return `Select the required filters first: ${{waiting.missing_inputs.join(", ")}}.`;
  return "No data is available for the selected filters and date range.";
}}
function funnelFiltersReady(currentFilters) {{
  const selected = key => String(currentFilters[key] || "").trim() && String(currentFilters[key]).toLowerCase() !== "all";
  const preset = String(currentFilters.date_preset || "").trim().toLowerCase();
  const hasDate = (preset && preset !== "all" && preset !== "custom") || (selected("date_from") && selected("date_to"));
  return selected("account_id") && hasDate;
}}
function tableHtml(rows, widget={{}}) {{
  if(!rows.length) return `<div class="empty">${{emptyStateMessage(widget)}}</div>`;
  const cols = Object.keys(rows[0] || {{}}).filter(c => !["metric_source","warnings"].includes(c));
  return `<div class="table-wrap"><table><thead><tr>${{cols.map(c=>`<th>${{c}}</th>`).join("")}}</tr></thead><tbody>${{rows.map(r=>`<tr>${{cols.map(c=>`<td>${{typeof r[c] === "object" ? JSON.stringify(r[c]) : (r[c] ?? "")}}</td>`).join("")}}</tr>`).join("")}}</tbody></table></div>`;
}}
function formatNumber(value) {{
  if(value === null || value === undefined || value === "") return "—";
  const number = Number(value); return Number.isFinite(number) ? number.toLocaleString(undefined,{{maximumFractionDigits:2}}) : String(value);
}}
function formatMoney(value) {{ return value === null || value === undefined ? "—" : formatNumber(value); }}
function formatRate(value) {{
  if(value === null || value === undefined || value === "") return "—";
  const number = Number(value); return Number.isFinite(number) ? `${{(number * 100).toFixed(1)}}%` : String(value);
}}
function funnelContract(widget) {{
  const configured = Array.isArray(widget.stages) ? widget.stages : (Array.isArray(widget.config?.stages) ? widget.config.stages : []);
  return configured.map(stage => {{
    if(typeof stage === "object") return stage;
    return (definition.stages || []).find(item => item.id === stage) || {{id:stage,label:stage,source:""}};
  }});
}}
function matchingStageRow(stage, rows) {{
  const exact = rows.find(row => row.id === stage.id);
  if(exact) return exact;
  const normalized = value => String(value || "").trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  const expected = normalized(stage.id);
  if(!expected) return null;
  return rows.find(row => {{
    const actual = normalized(row.id);
    return actual.startsWith(expected + "_") || expected.startsWith(actual + "_");
  }}) || null;
}}
function funnelHtml(widget, rows) {{
  const result = latestDataByQuery[queryIdForWidget(widget)] || latestData;
  const contract = funnelContract(widget);
  const ordered = contract.length
    ? contract.map(stage => ({{...(matchingStageRow(stage, rows) || {{}}),...stage}}))
    : rows;
  const queryError = result?.error;
  const waiting = (result?.node_status || []).find(item => item.status === "waiting_for_input");
  let state = "";
  if(queryError) state = `<div class="section-state error">Live data error: ${{queryError}}</div>`;
  else if(waiting) state = `<div class="section-state">Select: ${{(waiting.missing_inputs || []).join(", ")}}. The funnel structure will remain visible until live data is ready.</div>`;
  else if(!rows.length) state = `<div class="section-state">${{emptyStateMessage(widget)}}</div>`;
  const cards = ordered.map(stage => {{
    const missing = stage.source_status === "missing" || stage.numeric_value === null || stage.numeric_value === undefined;
    const details = (stage.details || []).map(item => `${{item.label || item.id}}: <b>${{formatNumber(item.value)}}</b>`).join(" · ");
    return `<article class="funnel-stage ${{missing ? "missing" : ""}}">
      <div class="stage-head"><div class="stage-name">${{stage.label || stage.id}}</div><span class="source-badge">${{stage.source || "source pending"}}</span></div>
      <div class="stage-number">${{formatNumber(stage.numeric_value ?? stage.value)}}</div>
      <div class="stage-metrics">
        <div class="stage-metric">Cost / stage<b>${{formatMoney(stage.cost)}}</b></div>
        <div class="stage-metric">Conversion<b>${{formatRate(stage.transition_rate)}}</b></div>
        <div class="stage-metric">Drop-off<b>${{formatRate(stage.drop_rate)}}</b></div>
        ${{stage.revenue !== null && stage.revenue !== undefined ? `<div class="stage-metric">Revenue<b>${{formatMoney(stage.revenue)}}</b></div>` : ""}}
        ${{stage.roas !== null && stage.roas !== undefined ? `<div class="stage-metric">ROAS<b>${{formatNumber(stage.roas)}}x</b></div>` : ""}}
      </div>
      ${{details ? `<div class="stage-details">${{details}}</div>` : ""}}
    </article>`;
  }}).join("");
  return `${{state}}<div class="funnel-flow">${{cards}}</div>`;
}}
function renderWidget(widget) {{
  const rows = widgetRows(widget);
  const type = widget.type || "table";
  const title = widget.title || widget.id || type;
  if(isControlWidget(widget)) return "";
  if(type === "status") {{
    const result = latestDataByQuery[queryIdForWidget(widget)] || latestData;
    const failed = result?.error || (result?.node_status || []).some(item => item.status === "failed");
    const waiting = (result?.node_status || []).some(item => item.status === "waiting_for_input") || result?.status === "waiting_for_filters";
    const state = failed ? "Connection error" : (waiting ? "Waiting for filters" : "Live data connected");
    const color = failed ? "#b42318" : (waiting ? "#b54708" : "#067647");
    return `<div class="panel ${{spanClass(widget)}}"><h3>${{title}}</h3><div style="font-size:18px;font-weight:800;color:${{color}}">● ${{state}}</div><div class="src">${{(widget.config?.sources || []).join(" · ")}}</div></div>`;
  }}
  if(type === "kpi") {{
    const stage = rows.find(s => s.id === widget.stage || s.id === widget.metric || s.id === widget.metric_id) || rows[0] || {{}};
    return `<div class="panel ${{spanClass(widget)}}"><div class="muted">${{title}}</div><div class="value">${{stage.value ?? stage.numeric_value ?? "-"}}</div><div class="src">${{stage.source || ""}}</div></div>`;
  }}
  if(["conversion_path","funnel"].includes(type)) {{
    return `<div class="panel ${{spanClass(widget)}}"><h3>${{title}}</h3>${{funnelHtml(widget, rows)}}</div>`;
  }}
  if(["bar","line","trend"].includes(type)) {{
    if(!rows.length) return `<div class="panel ${{spanClass(widget)}}"><h3>${{title}}</h3><div class="empty">${{emptyStateMessage(widget)}}</div></div>`;
    return `<div class="panel ${{spanClass(widget)}}"><h3>${{title}}</h3><div id="chart_${{widget.id}}" class="chart"></div></div>`;
  }}
  if(type === "text") return `<div class="panel ${{spanClass(widget)}}"><h3>${{title}}</h3><p>${{widget.text || widget.config?.text || ""}}</p></div>`;
  return `<div class="panel ${{spanClass(widget)}}"><h3>${{title}}</h3>${{tableHtml(rows, widget)}}</div>`;
}}
function drawCharts() {{
  (definition.widgets || []).forEach(widget => {{
    if(!["bar","line","trend"].includes(widget.type)) return;
    const el = document.getElementById("chart_" + widget.id); if(!el) return;
    const chart = charts[widget.id] || echarts.init(el); charts[widget.id] = chart;
    const rows = widgetRows(widget);
    chart.setOption({{
      tooltip:{{trigger:"axis"}},
      xAxis:{{type:"category",data:rows.map(r=>r.label || r.id), axisLabel:{{rotate:25}}}},
      yAxis:{{type:"value"}},
      series:[{{type: ["line","trend"].includes(widget.type) ? "line" : "bar", smooth:true, data:rows.map(r=>r.numeric_value || r.value || 0), itemStyle:{{color:"#2563eb"}}}}]
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
    const widgets = definition.widgets || [];
    const queryIds = new Set(widgets.map(queryIdForWidget));
    const filterQueryIds = new Set(effectiveFilters().map(queryIdForFilter).filter(Boolean));
    filterQueryIds.forEach(queryId => queryIds.add(queryId));
    if(definition.runtime_queries && definition.runtime_queries.global_filters) queryIds.add("global_filters");
    if(!queryIds.size) queryIds.add("journey_funnel");
    // A dashboard refresh must hydrate the parent options as well as child
    // options. The runtime still waits for missing required inputs, so this
    // does not issue campaign/ad set/ad calls until their parent is selected.
    const trigger = "always";
    const currentFilters = filters();
    const responses = await Promise.all([...queryIds].map(async queryId => {{
      const plan = definition.runtime_queries && definition.runtime_queries[queryId];
      const isControlQuery = filterQueryIds.has(queryId) || Boolean(plan && (plan.nodes || []).some(node => node.connector === "meta" && node.operation === "list_accounts"));
      if(!isControlQuery && !funnelFiltersReady(currentFilters)) {{
        return [queryId, {{status:"waiting_for_filters", node_status:[{{status:"waiting_for_input", missing_inputs:["account_id","date_from","date_to"]}}]}}];
      }}
      try {{
        return [queryId, await api("/api/dashboard-runtime/query", {{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{dashboard_id:definition.dashboard_id, query_id:queryId, filters:currentFilters, context:{{trigger}}}})}})];
      }} catch(error) {{ return [queryId, {{error:String(error.message || error)}}]; }}
    }}));
    latestDataByQuery = Object.fromEntries(responses);
    queryErrors = Object.fromEntries(responses.filter(([, value]) => value && value.error));
    const filterResults = Object.entries(latestDataByQuery)
      .filter(([, result]) => result && !result.error && Object.values(result.nodes || {{}}).some(node => Array.isArray(node?.data)))
      .map(([, result]) => result);
    let filterOptionsChanged = false;
    filterResults.forEach(result => {{ if(updateRuntimeFilterOptions(result)) filterOptionsChanged = true; }});
    if(filterOptionsChanged) renderFilters();
    latestData = latestDataByQuery.journey_funnel || Object.values(latestDataByQuery).find(value => value && !value.error) || null;
    hasLoadedDashboard = true;
    const errors = Object.entries(queryErrors);
    if(errors.length) document.getElementById("errorBox").innerHTML = `<div class="panel error">${{errors.map(([id, value]) => `${{id}}: ${{value.error}}`).join("<br>")}}</div>`;
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
    saved = _dashboard_store().save_definition(definition, dashboard_id)
    return {"success": True, "definition": saved, "url": _dashboard_url(saved["dashboard_id"])}


def _save_code_dashboard(dashboard: dict[str, Any], dashboard_id: str | None = None) -> dict:
    saved = _dashboard_store().save_code(dashboard, dashboard_id)
    return {"success": True, "dashboard": saved, "url": _code_dashboard_url(saved["dashboard_id"])}


def _stored_dashboard_row(dashboard_id: str) -> dict | None:
    return _dashboard_store().stored_row(dashboard_id)


def _stored_definition(dashboard_id: str) -> dict | None:
    return _dashboard_store().stored_definition(dashboard_id)


def _stored_code_dashboard(dashboard_id: str) -> dict | None:
    return _dashboard_store().stored_code(dashboard_id)


def _get_dashboard_definition(dashboard_id: str) -> dict | None:
    return _dashboard_store().get_definition(dashboard_id)


def _get_code_dashboard(dashboard_id: str) -> dict | None:
    return _dashboard_store().get_code(dashboard_id)


def _definition_from_code_dashboard(dashboard: dict[str, Any]) -> dict:
    return DashboardStore.definition_from_code(dashboard)


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
    definition = _get_dashboard_definition(dashboard_id)
    if definition:
        return definition
    if dashboard_id == DEFAULT_DASHBOARD_DEFINITION["dashboard_id"]:
        return DEFAULT_DASHBOARD_DEFINITION
    raise HTTPException(status_code=404, detail="Dashboard definition was not found.")


@router.put("/api/dashboard-definitions/{dashboard_id}", operation_id="update_dashboard_definition_manifest_v1")
async def update_dashboard_definition(dashboard_id: str, body: DashboardDefinitionUpdateRequest):
    definition = body.model_dump()
    return _save_dashboard_definition(definition, dashboard_id=dashboard_id)


@router.put("/api/dashboard-definitions/v2/{dashboard_id}", operation_id="update_dashboard_manifest_v2")
async def update_dashboard_definition_v2(dashboard_id: str, body: DashboardDefinitionUpdateRequest):
    definition = body.model_dump()
    return _save_dashboard_definition(definition, dashboard_id=dashboard_id)


@router.post("/api/dashboard-code/v1", operation_id="create_full_code_dashboard_v1")
async def create_code_dashboard(body: DashboardCodeRequest):
    dashboard = body.model_dump()
    return _save_code_dashboard(dashboard)


@router.get("/api/dashboard-code/v1/{dashboard_id}", operation_id="get_full_code_dashboard_v1")
async def get_code_dashboard(dashboard_id: str):
    dashboard = _get_code_dashboard(dashboard_id)
    if not dashboard:
        raise HTTPException(status_code=404, detail="Code dashboard was not found.")
    return dashboard


@router.put("/api/dashboard-code/v1/{dashboard_id}", operation_id="update_full_code_dashboard_v1")
async def update_code_dashboard(dashboard_id: str, body: DashboardCodeUpdateRequest):
    dashboard = body.model_dump()
    return _save_code_dashboard(dashboard, dashboard_id=dashboard_id)


@router.post("/api/dashboard-runtime/query")
async def dashboard_runtime_query(body: DashboardRuntimeQueryRequest, request: Request):
    dashboard_id = str(body.dashboard_id or "customer_journey")
    query_id = str(body.query_id or "journey_funnel")
    filters = body.filters or {}
    definition = _runtime_definition(dashboard_id, body.context)
    if definition.get("_runtime_resolution") == "not_found":
        raise HTTPException(status_code=404, detail="Dashboard runtime definition was not found.")
    saved_query = (definition.get("runtime_queries") or {}).get(query_id)
    if isinstance(saved_query, dict):
        plan = compile_runtime_query(query_id, saved_query)
        if plan:
            trigger = str(body.context.get("trigger") or "manual")
            return await execute_universal_dashboard_plan(plan, request, filters, trigger)
        connector = str(saved_query.get("connector") or saved_query.get("source") or "").strip().casefold()
        resource = str(saved_query.get("resource") or saved_query.get("operation") or saved_query.get("query") or query_id).strip().casefold()
        if connector == "journey":
            if resource in {"funnel", "journey_funnel", "blended_journey", "meta_insights"}:
                return await _live_or_fallback_funnel(request, filters, definition)
            if resource in {"trend", "funnel_trend", "journey_trend"}:
                return trend(filters=filters)
            if resource in {"comparison", "journey_comparison"}:
                return comparison()
            if resource in {"tracking_gap", "tracking_integrity"}:
                return await _live_or_fallback_funnel(request, filters, definition)
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Dashboard runtime query descriptor is not executable.",
                "dashboard_id": dashboard_id,
                "query_id": query_id,
                "connector": connector,
                "resource": resource,
            },
        )
    if saved_query is not None:
        raise HTTPException(status_code=422, detail="Dashboard runtime query must be an object.")
    if query_id in {"journey_funnel", "blended_journey", "dashboard_bootstrap", "meta_insights", "ga4_report", "clarity_behavior", "source_breakdown", "stage_detail"}:
        return await _live_or_fallback_funnel(request, filters, definition)
    if query_id == "journey_trend":
        return trend(filters=filters)
    if query_id == "journey_comparison":
        return comparison()
    if definition.get("runtime_queries"):
        raise HTTPException(
            status_code=404,
            detail={"message": "Dashboard runtime query was not found.", "dashboard_id": dashboard_id, "query_id": query_id},
        )
    return {"definition": definition, "query_plan": build_query_plan(definition, query_id), "filters": filters}


def _runtime_definition(dashboard_id: str, context: dict | None = None) -> dict:
    return _dashboard_store().runtime_definition(dashboard_id, DEFAULT_DASHBOARD_DEFINITION, context)


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
    debug = {
        "connector_errors": [],
        "connector_status": {"meta": "not_attempted", "ga4": "not_attempted", "clarity": "not_attempted"},
        "filters_sent": filters,
        "mode": "live_data_required",
    }
    token = None
    try:
        token = await resolve_access_token(request)
    except HTTPException as exc:
        debug["connector_errors"].append({"source": "meta", "stage": "auth", "error": exc.detail})
        debug["connector_status"]["meta"] = "auth_failed"
    if not token:
        optional_payload = _optional_sources_payload(filters, definition, request, debug)
        if optional_payload:
            debug["mode"] = "mixed_live_data"
            return build_mixed_funnel(optional_payload, filters, debug=debug, definition=definition)
        return _unavailable_live_funnel(filters, definition, debug)

    try:
        meta_payload, meta_debug = _fetch_live_meta_funnel(filters, definition, token)
        debug.update(meta_debug)
        _attach_live_ga4_and_clarity(meta_payload, filters, definition, request, debug)
        debug["mode"] = "live_data"
        debug["connector_status"]["meta"] = "success"
        return build_mixed_funnel(meta_payload, filters, debug=debug, definition=definition)
    except HTTPException as exc:
        debug["connector_errors"].append({"source": "meta", "stage": "insights", "error": exc.detail})
        debug["connector_status"]["meta"] = "failed"
    except Exception as exc:
        debug["connector_errors"].append({"source": "meta", "stage": "insights", "error": str(exc)})
        debug["connector_status"]["meta"] = "failed"
    optional_payload = _optional_sources_payload(filters, definition, request, debug)
    if optional_payload:
        debug["mode"] = "mixed_live_data"
        return build_mixed_funnel(optional_payload, filters, debug=debug, definition=definition)
    return _unavailable_live_funnel(filters, definition, debug)


def _unavailable_live_funnel(filters: dict, definition: dict, debug: dict) -> dict:
    """Return an explicit source error; never substitute demonstration metrics."""
    return {
        "dashboard_id": definition.get("dashboard_id"),
        "query_id": "journey_funnel",
        "status": "source_error",
        "complete": False,
        "filters": filters,
        "stages": [],
        "data": {"stages": [], "complete": False},
        "warnings": [],
        "errors": debug.get("connector_errors") or [],
        "connector_status": debug.get("connector_status") or {},
        "debug": {
            **debug,
            "mode": "live_data_unavailable",
            "message": "No demonstration or fallback metrics were used. Connect and validate the required live sources.",
        },
    }


def _optional_sources_payload(filters: dict, definition: dict, request: Request, debug: dict) -> dict | None:
    payload = {"data": [{}]}
    _attach_live_ga4_and_clarity(payload, filters, definition, request, debug)
    if payload.get("_ga4_metrics") or payload.get("_clarity_metrics"):
        return payload
    return None


def _attach_live_ga4_and_clarity(meta_payload: dict, filters: dict, definition: dict, request: Request, debug: dict) -> None:
    _attach_live_ga4(meta_payload, filters, definition, request, debug)
    _attach_live_clarity(meta_payload, filters, request, debug)


def _attach_live_ga4(meta_payload: dict, filters: dict, definition: dict, request: Request, debug: dict) -> None:
    tenant_id = _runtime_tenant_id(filters, request)
    if not tenant_id:
        debug["connector_status"]["ga4"] = "skipped_no_tenant"
        return
    event_names = _ga4_event_names(definition)
    fields = _ga4_summary_fields(definition)
    page_specs = _ga4_page_specs(definition)
    if not event_names and not fields and not page_specs:
        debug["connector_status"]["ga4"] = "skipped_no_ga4_metrics"
        return
    property_id = _runtime_ga4_property_id(filters, definition)
    date_from, date_to = _runtime_date_range(filters)
    ga4_metrics = {"events": {}, "summary": {}, "page_metrics": {}, "rows": []}
    try:
        if event_names:
            event_payload = run_ga4_report(
                tenant_id,
                property_id,
                ["eventName"],
                ["eventCount"],
                date_from,
                date_to,
                limit=200,
            )
            event_rows = normalize_ga4_report(event_payload)
            ga4_metrics["events"] = {
                str(row.get("eventName") or ""): _to_number(row.get("eventCount"))
                for row in event_rows
                if row.get("eventName")
            }
            ga4_metrics["rows"].extend(event_rows)
            debug["ga4_property_id"] = event_payload.get("property_id")
        if fields:
            summary_payload = run_ga4_report(
                tenant_id,
                property_id,
                [],
                sorted(fields),
                date_from,
                date_to,
                limit=1,
            )
            summary_rows = normalize_ga4_report(summary_payload)
            if summary_rows:
                ga4_metrics["summary"].update(summary_rows[0])
            ga4_metrics["rows"].extend(summary_rows)
            debug["ga4_property_id"] = summary_payload.get("property_id")
        for page_spec in page_specs:
            page_path = page_spec["page_path_contains"]
            page_payload = run_ga4_report(
                tenant_id,
                property_id,
                ["pagePathPlusQueryString"],
                sorted(page_spec["metrics"]),
                date_from,
                date_to,
                limit=100,
                filters={"page_path_contains": page_path},
            )
            page_rows = normalize_ga4_report(page_payload)
            totals = {metric: sum(_to_number(row.get(metric)) for row in page_rows) for metric in page_spec["metrics"]}
            for metric, value in totals.items():
                ga4_metrics["page_metrics"][f"{page_path}:{metric}"] = value
            ga4_metrics["rows"].extend(page_rows)
            debug["ga4_property_id"] = page_payload.get("property_id")
        meta_payload["_ga4_metrics"] = ga4_metrics
        debug["connector_status"]["ga4"] = "success"
        debug["ga4_events_found"] = sorted(ga4_metrics["events"])
    except HTTPException as exc:
        debug["connector_status"]["ga4"] = "failed"
        debug["connector_errors"].append({"source": "ga4", "stage": "dashboard_runtime", "error": exc.detail})
    except Exception as exc:
        debug["connector_status"]["ga4"] = "failed"
        debug["connector_errors"].append({"source": "ga4", "stage": "dashboard_runtime", "error": str(exc)})


def _attach_live_clarity(meta_payload: dict, filters: dict, request: Request, debug: dict) -> None:
    tenant_id = _runtime_tenant_id(filters, request)
    if not tenant_id:
        debug["connector_status"]["clarity"] = "skipped_no_tenant"
        return
    try:
        payload = run_clarity_live_insights_with_fallbacks(
            tenant_id,
            _clarity_days(filters),
            _clarity_dimensions(filters),
        )
        rows = normalize_clarity_export(payload)
        meta_payload["_clarity_metrics"] = {"summary": summarize_clarity_metrics(rows), "rows": rows[:100]}
        debug["connector_status"]["clarity"] = "success"
        debug["clarity_dimensions"] = payload.get("dimensions")
        debug["clarity_fallback_used"] = payload.get("fallback_used")
    except HTTPException as exc:
        debug["connector_status"]["clarity"] = "failed"
        debug["connector_errors"].append({"source": "clarity", "stage": "dashboard_runtime", "error": exc.detail})
    except Exception as exc:
        debug["connector_status"]["clarity"] = "failed"
        debug["connector_errors"].append({"source": "clarity", "stage": "dashboard_runtime", "error": str(exc)})


def _runtime_tenant_id(filters: dict, request: Request) -> str | None:
    value = str(filters.get("tenant_id") or request.session.get("tenant_id") or "").strip()
    return value or None


def _runtime_ga4_property_id(filters: dict, definition: dict) -> str | None:
    value = str(filters.get("property_id") or filters.get("ga4_property_id") or "").strip()
    if value and value.lower() != "all":
        return value
    source = (definition.get("data_sources") or {}).get("ga4") or {}
    value = str(source.get("property_id") or source.get("ga4_property_id") or "").strip()
    return value or None


def _runtime_date_range(filters: dict) -> tuple[str, str]:
    date_from = str(filters.get("date_from") or filters.get("start_date") or "30daysAgo").strip()
    date_to = str(filters.get("date_to") or filters.get("end_date") or "today").strip()
    return date_from, date_to


def _ga4_event_names(definition: dict) -> set[str]:
    metrics = (definition.get("metrics") or {}) if isinstance(definition.get("metrics"), dict) else {}
    return {
        str(metric.get("event_name") or "").strip()
        for metric in metrics.values()
        if isinstance(metric, dict) and metric.get("source") in {"ga4", "ga4_event"} and metric.get("event_name")
    }


def _ga4_summary_fields(definition: dict) -> set[str]:
    metrics = (definition.get("metrics") or {}) if isinstance(definition.get("metrics"), dict) else {}
    return {
        str(metric.get("field") or metric.get("metric") or "").strip()
        for metric in metrics.values()
        if isinstance(metric, dict) and metric.get("source") == "ga4" and (metric.get("field") or metric.get("metric")) and not metric.get("page_path_contains")
    }


def _ga4_page_specs(definition: dict) -> list[dict]:
    metrics = (definition.get("metrics") or {}) if isinstance(definition.get("metrics"), dict) else {}
    specs = {}
    for metric in metrics.values():
        if not isinstance(metric, dict) or metric.get("source") != "ga4_page":
            continue
        page_path = str(metric.get("page_path_contains") or metric.get("focus_url") or "").strip()
        if not page_path:
            continue
        metric_names = metric.get("metrics") or [metric.get("metric") or metric.get("field") or "sessions"]
        bucket = specs.setdefault(page_path, set())
        bucket.update(str(item) for item in metric_names if item)
    return [{"page_path_contains": page_path, "metrics": values} for page_path, values in specs.items()]


def _clarity_days(filters: dict) -> int:
    value = filters.get("clarity_num_of_days") or filters.get("num_of_days") or 1
    try:
        return min(max(int(value), 1), 3)
    except (TypeError, ValueError):
        return 1


def _clarity_dimensions(filters: dict) -> list[str]:
    dimensions = filters.get("clarity_dimensions")
    if isinstance(dimensions, list) and dimensions:
        return [str(item) for item in dimensions[:3]]
    return ["Campaign", "URL", "Device"]


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
    selected_account_id = str(filters.get("account_id") or "").strip()
    if selected_account_id and selected_account_id.casefold() != "all":
        clean_selected = selected_account_id if selected_account_id.startswith("act_") else f"act_{selected_account_id}"
        return clean_selected, {"type": "account", "id": clean_selected}
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
