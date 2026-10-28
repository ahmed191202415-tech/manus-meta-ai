"""Explicitly gated MCP change operations.

Writes reuse the project's existing validated REST endpoints. No external
operation happens until the connecting client submits a confirmed action
and the operator explicitly enables MCP writes in the server environment.
"""
import os

from app.schemas.meta_requests import (
    RawMetaRequest, CampaignCreateRequest, AdSetCreateRequest,
    AdCreateRequest, CreativeCreateRequest, CustomAudienceCreateRequest,
    PixelCreateRequest,
)
from app.schemas.comment_automation_requests import CommentAutomationManageRequest
from app.schemas.page_requests import PagePostCreateRequest, CommentReplyRequest


def require_write(confirmed: bool):
    if os.getenv("MCP_WRITES_ENABLED", "").lower() not in {"1", "true", "yes"}:
        raise ValueError("MCP writes are disabled; enable MCP_WRITES_ENABLED explicitly.")
    if confirmed is not True:
        raise ValueError("Show the exact proposed action to the user and obtain explicit approval before making this change.")


def register_action_tools(mcp, post):
    """Register authorized Meta ad, Page and comment operations."""

    @mcp.tool()
    async def create_meta_asset(kind: str, values: dict, confirmed: bool = False) -> dict:
        """Create a Meta campaign, adset, ad, creative, pixel, or audience.
        Provide validated API fields. Campaigns, Ad Sets and Ads default PAUSED.
        Requires human approval and write access.
        """
        require_write(confirmed)
        models = {
            "campaign": (CampaignCreateRequest, "/campaigns"),
            "adset": (AdSetCreateRequest, "/adsets"),
            "ad": (AdCreateRequest, "/ads"),
            "creative": (CreativeCreateRequest, "/adcreatives"),
            "pixel": (PixelCreateRequest, "/pixels"),
            "audience": (CustomAudienceCreateRequest, "/custom_audiences"),
        }
        if kind not in models:
            raise ValueError("kind must be campaign, adset, ad, creative, pixel or audience")
        model, endpoint = models[kind]
        body = model.model_validate(values)
        return await post(endpoint, body.model_dump(exclude_none=True))

    @mcp.tool()
    async def update_meta_asset(method: str, path: str, values: dict | None = None,
                                page_id: str = "", confirmed: bool = False) -> dict:
        """Change campaign/adset/ad status, budgets, targeting, creative,
        Page objects or other Meta Graph entities. method is POST or DELETE.
        Confirm the exact target and data before executing.
        """
        require_write(confirmed)
        body = RawMetaRequest.model_validate({
            "method": method, "path": path, "data": values or {},
            "page_id": page_id or None,
        })
        return await post("/meta/request", body.model_dump(exclude_none=True))

    @mcp.tool()
    async def create_page_post(values: dict, confirmed: bool = False) -> dict:
        """Publish or schedule a Facebook Page post, using page_id and message,
        link or media. Get explicit approval of the final post first.
        """
        require_write(confirmed)
        body = PagePostCreateRequest.model_validate(values)
        return await post("/page_posts", body.model_dump(exclude_none=True))

    @mcp.tool()
    async def reply_to_page_comment(page_id: str, comment_id: str, message: str,
                                    confirmed: bool = False) -> dict:
        """Reply publicly to a Facebook Page comment after approving the text."""
        require_write(confirmed)
        CommentReplyRequest.model_validate({"message": message})
        return await post("/page_comments/" + comment_id + "/reply?page_id=" + page_id,
                          {"message": message})

    @mcp.tool()
    async def moderate_page_comment(page_id: str, comment_id: str,
                                    hidden: bool = True, confirmed: bool = False) -> dict:
        """Hide or unhide a Facebook Page comment after approval."""
        require_write(confirmed)
        return await post("/page_comments/" + comment_id + "/hide?page_id=" + page_id,
                          {"is_hidden": hidden})

    @mcp.tool()
    async def page_comment_automation(action: str, values: dict | None = None,
                                      confirmed: bool = False) -> dict:
        """Read/manage Page comment rules, keyword replies, private replies,
        webhook subscriptions, logs, verified ad scopes and post aliases.
        Read actions need no approval; all changes do.
        """
        read_actions = {
            "list_pages", "list_posts", "list_comments", "list_rules",
            "list_logs", "diagnose_page", "list_unmapped_posts", "list_post_aliases",
        }
        if action not in read_actions:
            require_write(confirmed)
        body = CommentAutomationManageRequest.model_validate({
            **(values or {}), "action": action,
        })
        return await post("/comment_automations/manage", body.model_dump(exclude_none=True))
