"""MCP adapters for reports, datasets and declarative dashboard workflows."""
from app.schemas.gpt_tool_requests import ReportToolRequest, DashboardToolRequest
from app.schemas.dashboard_runtime_requests import DashboardRuntimeWorkflowRequest
from app.mcp_actions import require_write


def register_reporting_tools(mcp, post):

    @mcp.tool()
    async def generate_report(action: str, values: dict, confirmed: bool = False) -> dict:
        """Create PDF, Excel, PPTX, DOCX or HTML reports and website/journey
        report exports from structured data. Approve before writing files.
        """
        require_write(confirmed)
        body = ReportToolRequest.model_validate({"action": action, "payload": values})
        return await post("/tools/reports", body.model_dump(exclude_none=True))

    @mcp.tool()
    async def manage_dashboards(action: str, values: dict | None = None,
                                confirmed: bool = False) -> dict:
        """Create, list, update, delete and refresh dashboards and tenant
        datasets; insert, query or delete dataset records.
        """
        if action not in {"list_dashboards", "list_datasets", "query_dataset"}:
            require_write(confirmed)
        body = DashboardToolRequest.model_validate({"action": action, "payload": values or {}})
        return await post("/tools/dashboards", body.model_dump(exclude_none=True))

    @mcp.tool()
    async def dashboard_runtime(action: str, values: dict | None = None,
                                confirmed: bool = False) -> dict:
        """Execute universal dashboard runtime workflow:
        capabilities, validate, preview, execute, publish_section.
        Publishing requires a preview confirmation token and approval.
        """
        if action == "publish_section":
            require_write(confirmed)
        body = DashboardRuntimeWorkflowRequest.model_validate({
            **(values or {}), "action": action,
        })
        return await post("/api/dashboard-runtime/v2/workflow",
                          body.model_dump(exclude_none=True))

