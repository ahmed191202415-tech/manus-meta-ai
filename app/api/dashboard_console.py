from __future__ import annotations

from html import escape
import json
import secrets

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import ValidationError

from app.api.dashboard_runtime import publish_confirmed_dashboard_section
from app.core.dashboard_runtime import create_confirmation_token, execute_plan
from app.schemas.dashboard_runtime_requests import DashboardQueryPlan, DashboardSectionPublishRequest


router = APIRouter(prefix="/dashboard-runtime", tags=["dashboard-runtime-console"])


def _tenant_id(request: Request) -> str:
    tenant_id = str(request.session.get("tenant_id") or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Open the tenant portal and verify the email first.")
    return tenant_id


def _csrf_token(request: Request) -> str:
    token = str(request.session.get("dashboard_console_csrf") or "")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["dashboard_console_csrf"] = token
    return token


def _verify_csrf(request: Request, token: str) -> None:
    expected = str(request.session.get("dashboard_console_csrf") or "")
    if not expected or not secrets.compare_digest(expected, str(token or "")):
        raise HTTPException(status_code=403, detail="Invalid dashboard console form token.")


def _page(title: str, content: str) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title><style>
body{{font-family:Arial,sans-serif;background:#f4f7fb;color:#172033;margin:0}}main{{max-width:1180px;margin:auto;padding:24px}}
.card{{background:white;border:1px solid #dbe3ef;border-radius:12px;padding:18px;margin:14px 0;box-shadow:0 8px 24px #1720330d}}
textarea,input,select,button{{width:100%;box-sizing:border-box;padding:10px;margin:6px 0 12px;border:1px solid #cbd5e1;border-radius:8px;font:inherit}}
textarea{{min-height:220px;font-family:Consolas,monospace;direction:ltr}}button{{background:#135ee8;color:white;border:0;font-weight:700;cursor:pointer}}
pre{{white-space:pre-wrap;word-break:break-word;background:#0f172a;color:#e2e8f0;padding:14px;border-radius:9px;max-height:600px;overflow:auto;direction:ltr}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}label{{font-weight:700}}.muted{{color:#64748b}}a{{color:#135ee8}}
@media(max-width:800px){{.grid{{grid-template-columns:1fr}}}}
</style></head><body><main>{content}</main></body></html>"""
    )


def _json_object(raw: str, label: str) -> dict:
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"{label} must be valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=422, detail=f"{label} must be a JSON object.")
    return value


@router.get("/console", response_class=HTMLResponse, include_in_schema=False)
async def dashboard_runtime_console(request: Request):
    tenant_id = _tenant_id(request)
    csrf = _csrf_token(request)
    return _page(
        "Universal Dashboard Runtime Console",
        f"""<section class="card"><h1>Universal Dashboard Runtime Console</h1>
<p class="muted">Tenant: {escape(tenant_id)}. This console executes the same safe declarative plans used by GPT.</p></section>
<section class="card"><h2>Live preview</h2><form method="post" action="/dashboard-runtime/console/preview">
<input type="hidden" name="csrf_token" value="{escape(csrf)}"><label>Query plan JSON</label><textarea name="plan_json" required>{{}}</textarea>
<div class="grid"><div><label>Inputs JSON</label><textarea name="inputs_json">{{}}</textarea></div><div><label>Trigger</label>
<select name="trigger"><option>manual</option><option>always</option><option>on_open</option><option>on_change</option></select></div></div>
<button type="submit">Run live preview</button></form></section>""",
    )


@router.post("/console/preview", response_class=HTMLResponse, include_in_schema=False)
async def dashboard_runtime_console_preview(
    request: Request,
    csrf_token: str = Form(...),
    plan_json: str = Form(...),
    inputs_json: str = Form("{}"),
    trigger: str = Form("manual"),
):
    _tenant_id(request)
    _verify_csrf(request, csrf_token)
    try:
        plan = DashboardQueryPlan.model_validate(_json_object(plan_json, "plan_json"))
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    inputs = _json_object(inputs_json, "inputs_json")
    result = await execute_plan(plan, request, inputs, trigger)
    confirmation_token = create_confirmation_token(plan, result)
    csrf = _csrf_token(request)
    result_text = escape(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    plan_text = escape(json.dumps(plan.model_dump(), ensure_ascii=False, indent=2))
    token_text = escape(confirmation_token)
    return _page(
        "Dashboard Preview",
        f"""<section class="card"><h1>Live preview</h1><pre>{result_text}</pre></section>
<section class="card"><h2>Publish this exact preview</h2><form method="post" action="/dashboard-runtime/console/publish">
<input type="hidden" name="csrf_token" value="{escape(csrf)}"><label>Dashboard ID</label><input name="dashboard_id" required>
<div class="grid"><div><label>Section ID</label><input name="section_id" required></div><div><label>Title</label><input name="title" required></div></div>
<label>Presentation JSON</label><textarea name="presentation_json" required>{{}}</textarea>
<label>Confirmed query plan</label><textarea name="plan_json" readonly>{plan_text}</textarea>
<label>Confirmation token</label><textarea name="confirmation_token" readonly>{token_text}</textarea>
<button type="submit">Publish confirmed section</button></form></section>""",
    )


@router.post("/console/publish", response_class=HTMLResponse, include_in_schema=False)
async def dashboard_runtime_console_publish(
    request: Request,
    csrf_token: str = Form(...),
    dashboard_id: str = Form(...),
    section_id: str = Form(...),
    title: str = Form(...),
    presentation_json: str = Form(...),
    plan_json: str = Form(...),
    confirmation_token: str = Form(...),
):
    _tenant_id(request)
    _verify_csrf(request, csrf_token)
    try:
        body = DashboardSectionPublishRequest(
            dashboard_id=dashboard_id,
            section_id=section_id,
            title=title,
            presentation=_json_object(presentation_json, "presentation_json"),
            query_plan=DashboardQueryPlan.model_validate(_json_object(plan_json, "plan_json")),
            confirmation_token=confirmation_token,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    result = await publish_confirmed_dashboard_section(body, request)
    result_text = escape(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    dashboard_url = f"/dashboards/custom/{escape(dashboard_id)}"
    return _page(
        "Dashboard Section Published",
        f"""<section class="card"><h1>Section published</h1><p><a href="{dashboard_url}">Open dashboard</a></p><pre>{result_text}</pre></section>""",
    )
