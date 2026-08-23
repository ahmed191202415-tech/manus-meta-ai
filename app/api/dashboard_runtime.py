from fastapi import APIRouter, HTTPException, Request

from app.api import journey_dashboard_v7
from app.core.dashboard_runtime import (
    connector_catalog,
    create_confirmation_token,
    execute_plan,
    validate_plan,
    verify_confirmation_token,
)
from app.schemas.dashboard_runtime_requests import (
    DashboardPlanPreviewRequest,
    DashboardPlanValidateRequest,
    DashboardSavedQueryExecuteRequest,
    DashboardSectionPublishRequest,
    DashboardRuntimeWorkflowRequest,
)
from app.core.oauth_store import get_app_token_data


router = APIRouter(prefix="/api/dashboard-runtime/v2", tags=["universal-dashboard-runtime"])


@router.post("/workflow", operation_id="universal_dashboard_runtime_workflow_v2")
async def universal_dashboard_runtime_workflow(body: DashboardRuntimeWorkflowRequest, request: Request):
    """Single ChatGPT dispatcher: inspect, validate, preview, execute, or publish any dashboard section."""
    if body.action == "capabilities":
        return connector_catalog()
    if not body.plan:
        raise HTTPException(status_code=422, detail="plan is required for this action.")
    if body.action == "validate":
        return validate_plan(body.plan)
    if body.action == "preview":
        result = await execute_plan(body.plan, request, body.inputs, body.trigger)
        return {
            "status": "awaiting_user_confirmation",
            "plan": body.plan.model_dump(),
            "preview": result,
            "confirmation_token": create_confirmation_token(body.plan, result),
            "next_step": "Show the preview to the user and wait for explicit confirmation before publish_section.",
        }
    if body.action == "execute":
        return await execute_plan(body.plan, request, body.inputs, body.trigger)
    missing = [key for key, value in {
        "dashboard_id": body.dashboard_id,
        "section_id": body.section_id,
        "title": body.title,
        "confirmation_token": body.confirmation_token,
    }.items() if not value]
    if missing:
        raise HTTPException(status_code=422, detail={"message": "Publishing fields are missing.", "missing": missing})
    publish_body = DashboardSectionPublishRequest(
        dashboard_id=body.dashboard_id,
        section_id=body.section_id,
        title=body.title,
        query_plan=body.plan,
        presentation=body.presentation,
        confirmation_token=body.confirmation_token,
    )
    return await publish_confirmed_dashboard_section(publish_body, request)


def _request_tenant_id(request: Request) -> str | None:
    tenant_id = str(request.session.get("tenant_id") or "").strip()
    if tenant_id:
        return tenant_id
    authorization = str(request.headers.get("authorization") or "")
    if authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        if token.startswith("app_"):
            try:
                return str((get_app_token_data(token) or {}).get("tenant_id") or "").strip() or None
            except Exception:
                return None
    return None


def _require_dashboard_owner(request: Request, dashboard_id: str, definition: dict) -> str:
    tenant_id = _request_tenant_id(request)
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Tenant authentication is required to publish a dashboard section.")
    row = journey_dashboard_v7._stored_dashboard_row(dashboard_id)
    owner = str((row or {}).get("tenant_id") or definition.get("tenant_id") or definition.get("owner_tenant_id") or "").strip()
    if owner and owner != tenant_id:
        raise HTTPException(status_code=403, detail="This dashboard belongs to another tenant.")
    return tenant_id


@router.get("/capabilities", operation_id="dashboard_runtime_capabilities_v2")
async def runtime_capabilities():
    """Return the safe operations ChatGPT may compose into any dashboard backend."""
    return connector_catalog()


@router.post("/validate", operation_id="validate_dashboard_query_plan_v2")
async def validate_dashboard_query_plan(body: DashboardPlanValidateRequest):
    """Validate a ChatGPT-generated backend plan without calling live data sources."""
    return validate_plan(body.plan)


@router.post("/preview", operation_id="preview_dashboard_query_plan_v2")
async def preview_dashboard_query_plan(body: DashboardPlanPreviewRequest, request: Request):
    """Run live data before a section is created and issue a short-lived confirmation token."""
    result = await execute_plan(body.plan, request, body.inputs, body.trigger)
    return {
        "status": "awaiting_user_confirmation",
        "plan": body.plan.model_dump(),
        "preview": result,
        "confirmation_token": create_confirmation_token(body.plan, result),
        "next_step": "Show the preview values, sources, filters, and errors to the user. Publish only after explicit confirmation.",
    }


@router.post("/execute", operation_id="execute_dashboard_query_plan_v2")
async def execute_dashboard_query_plan(body: DashboardPlanPreviewRequest, request: Request):
    """Execute a validated plan for a live dashboard refresh or filter change."""
    return await execute_plan(body.plan, request, body.inputs, body.trigger)


@router.post("/sections/publish", operation_id="publish_confirmed_dashboard_section_v2")
async def publish_confirmed_dashboard_section(body: DashboardSectionPublishRequest, request: Request):
    """Attach a confirmed query plan and presentation contract to a persistent dashboard."""
    verify_confirmation_token(body.confirmation_token, body.query_plan)
    definition = journey_dashboard_v7._get_dashboard_definition(body.dashboard_id)
    if not definition:
        raise HTTPException(status_code=404, detail="Dashboard definition was not found.")
    tenant_id = _require_dashboard_owner(request, body.dashboard_id, definition)
    updated = dict(definition)
    updated["tenant_id"] = tenant_id
    published_filters = body.presentation.get("filters")
    if isinstance(published_filters, list):
        existing_filters = {
            str(item.get("key") or ""): item
            for item in (updated.get("filters") or [])
            if isinstance(item, dict) and item.get("key")
        }
        for item in published_filters:
            if isinstance(item, dict) and item.get("key"):
                existing_filters[str(item["key"])] = item
        updated["filters"] = list(existing_filters.values())
    runtime_queries = dict(updated.get("runtime_queries") or {})
    runtime_queries[body.section_id] = body.query_plan.model_dump()
    updated["runtime_queries"] = runtime_queries
    widgets = [item for item in (updated.get("widgets") or []) if item.get("id") != body.section_id]
    widgets.append(
        {
            "id": body.section_id,
            "title": body.title,
            "data_query": body.section_id,
            **body.presentation,
        }
    )
    updated["widgets"] = widgets
    saved = journey_dashboard_v7._save_dashboard_definition(updated, dashboard_id=body.dashboard_id)
    return {
        **saved,
        "status": "published",
        "section_id": body.section_id,
        "query_plan": body.query_plan.model_dump(),
    }


@router.post("/{dashboard_id}/queries/{query_id}", operation_id="execute_saved_dashboard_query_v2")
async def execute_saved_dashboard_query(
    dashboard_id: str,
    query_id: str,
    body: DashboardSavedQueryExecuteRequest,
    request: Request,
):
    """Execute a plan saved by ChatGPT as the live backend of a dashboard section."""
    definition = journey_dashboard_v7._runtime_definition(dashboard_id)
    raw_plan = (definition.get("runtime_queries") or {}).get(query_id)
    if not raw_plan:
        raise HTTPException(status_code=404, detail="Dashboard query was not found.")
    validated_plan = DashboardPlanValidateRequest.model_validate({"plan": raw_plan}).plan
    return await execute_plan(validated_plan, request, body.inputs, body.trigger)
