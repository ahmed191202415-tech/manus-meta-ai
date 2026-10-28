"""Focused discovery tools for easy natural-language navigation of Meta assets."""

def register_discovery_tools(mcp, post):

    @mcp.tool()
    async def list_campaigns(account_id: str, limit: int = 50) -> dict:
        """List Meta advertising campaigns, statuses, objectives and budgets."""
        account = account_id if account_id.startswith("act_") else "act_" + account_id
        return await post("/meta/query", {"path": account + "/campaigns", "params": {
            "fields": "id,name,status,effective_status,objective,daily_budget,lifetime_budget,created_time",
            "limit": min(max(limit, 1), 100),
        }})

    @mcp.tool()
    async def list_ad_sets(account_id: str, limit: int = 50) -> dict:
        """List Ad Sets with budgets, targeting and optimization settings."""
        account = account_id if account_id.startswith("act_") else "act_" + account_id
        return await post("/meta/query", {"path": account + "/adsets", "params": {
            "fields": "id,name,campaign_id,status,effective_status,daily_budget,lifetime_budget,targeting,optimization_goal",
            "limit": min(max(limit, 1), 100),
        }})

    @mcp.tool()
    async def list_ads(account_id: str, limit: int = 50) -> dict:
        """List ads, their Ad Sets, creative references and delivery statuses."""
        account = account_id if account_id.startswith("act_") else "act_" + account_id
        return await post("/meta/query", {"path": account + "/ads", "params": {
            "fields": "id,name,campaign_id,adset_id,status,effective_status,creative,updated_time",
            "limit": min(max(limit, 1), 100),
        }})

    @mcp.tool()
    async def list_facebook_pages(limit: int = 50) -> dict:
        """List Facebook Pages available to the connected Meta account."""
        return await post("/meta/query", {"path": "me/accounts", "params": {
            "fields": "id,name,category,fan_count,followers_count",
            "limit": min(max(limit, 1), 100),
        }})

    @mcp.tool()
    async def list_page_posts(page_id: str, limit: int = 30) -> dict:
        """List posts published by a managed Facebook Page."""
        return await post("/meta/query", {"page_id": page_id,
            "path": page_id + "/posts", "params": {
                "fields": "id,message,created_time,permalink_url",
                "limit": min(max(limit, 1), 100),
            }})

    @mcp.tool()
    async def list_page_comments(page_id: str, post_id: str, limit: int = 50) -> dict:
        """List comments and moderation states on a Facebook Page post."""
        return await post("/meta/query", {"page_id": page_id,
            "path": post_id + "/comments", "params": {
                "fields": "id,from,message,created_time,like_count,comment_count,is_hidden",
                "limit": min(max(limit, 1), 100),
            }})
