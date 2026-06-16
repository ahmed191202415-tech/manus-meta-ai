from json import dumps

from fastapi import APIRouter, Body, Query
from fastapi.responses import HTMLResponse

from app.analytics.dashboard_engine import (
    CONNECTOR_REGISTRY,
    DEFAULT_DASHBOARD_DEFINITION,
    METRIC_DICTIONARY,
    build_fallback_funnel,
    build_query_plan,
    comparison,
    filter_options,
    stage_detail,
    trend,
)

router = APIRouter(tags=["journey-dashboard-v7"])

_DEFINITIONS = {DEFAULT_DASHBOARD_DEFINITION["dashboard_id"]: DEFAULT_DASHBOARD_DEFINITION}


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
const definition = {definition_json};
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
  const data = await api("/api/journey/funnel?" + new URLSearchParams(filters()));
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
loadFilters().then(reloadAll);
</script>
</body>
</html>""")


@router.post("/api/dashboard-definitions")
async def create_dashboard_definition(body: dict = Body(...)):
    dashboard_id = str(body.get("dashboard_id") or "custom_dashboard")
    body["dashboard_id"] = dashboard_id
    _DEFINITIONS[dashboard_id] = body
    return {"success": True, "definition": body}


@router.get("/api/dashboard-definitions/{dashboard_id}")
async def get_dashboard_definition(dashboard_id: str):
    return _DEFINITIONS.get(dashboard_id, DEFAULT_DASHBOARD_DEFINITION)


@router.put("/api/dashboard-definitions/{dashboard_id}")
async def update_dashboard_definition(dashboard_id: str, body: dict = Body(...)):
    body["dashboard_id"] = dashboard_id
    _DEFINITIONS[dashboard_id] = body
    return {"success": True, "definition": body}


@router.post("/api/dashboard-runtime/query")
async def dashboard_runtime_query(body: dict = Body(...)):
    dashboard_id = str(body.get("dashboard_id") or "customer_journey")
    query_id = str(body.get("query_id") or "journey_funnel")
    filters = body.get("filters") or {}
    definition = _DEFINITIONS.get(dashboard_id, DEFAULT_DASHBOARD_DEFINITION)
    if query_id == "journey_funnel":
        return build_fallback_funnel(filters)
    if query_id == "journey_trend":
        return trend(filters=filters)
    if query_id == "journey_comparison":
        return comparison()
    return {"definition": definition, "query_plan": build_query_plan(definition, query_id), "filters": filters}


@router.get("/api/dashboard-runtime/connectors")
async def dashboard_connectors():
    return {"connectors": CONNECTOR_REGISTRY, "metrics": METRIC_DICTIONARY}


@router.get("/api/journey/filters")
async def journey_filters():
    return filter_options()


@router.get("/api/journey/funnel")
async def journey_funnel(
    date_from: str | None = None,
    date_to: str | None = None,
    campaign_id: str = "all",
    adset_id: str = "all",
    ad_id: str = "all",
    device: str = "all",
    placement: str = "all",
):
    return build_fallback_funnel(locals())


@router.get("/api/journey/stage-detail")
async def journey_stage_detail(stage_id: str = Query(...), date_from: str | None = None, date_to: str | None = None, campaign_id: str = "all", adset_id: str = "all", ad_id: str = "all", device: str = "all"):
    return stage_detail(stage_id, locals())


@router.get("/api/journey/trend")
async def journey_trend(stage_id: str = "register_page", metric: str = "value", granularity: str = "daily", level: str = "campaign", campaign_id: str = "all"):
    return trend(stage_id=stage_id, metric=metric, filters={"campaign_id": campaign_id, "granularity": granularity, "level": level})


@router.post("/api/journey/comparison")
async def journey_comparison(body: dict = Body(default_factory=dict)):
    return comparison(
        entities=body.get("entities"),
        stage_id=body.get("stage_id", "register_page"),
        metric=body.get("metric", "cost"),
        sort=body.get("sort", "lowest_cost"),
    )
