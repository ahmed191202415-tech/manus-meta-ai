# MCP capability coverage matrix

This is a code-level routing audit, not a claim of live Meta/GA4 account access. Existing FastAPI handlers remain canonical.

| Existing API family | MCP tool(s) | Scope |
|---|---|---|
| /accounts, /campaigns, /adsets, /ads | discover_accounts, list_campaigns, list_ad_sets, list_ads | Ad account and delivery discovery |
| /meta/query | meta_graph_read | Read-only Meta Graph objects, insights, Pages, Instagram, leads, creative |
| /meta/smart_insights | meta_insights | Resilient performance reports |
| /analysis/run | run_analysis, run_advanced_analysis | All analysis modes and financial inputs |
| /meta/request | update_meta_asset | Meta Graph POST / DELETE operations (gated) |
| /campaigns, /adsets, /ads, /adcreatives | create_meta_asset | Typed entity creation (gated) |
| /custom_audiences, /pixels | create_meta_asset | Typed audience and Pixel creation (gated) |
| /page_posts | create_page_post | Facebook Page post publishing/scheduling (gated) |
| /page_comments | reply_to_page_comment, moderate_page_comment | Public reply, hide/unhide (gated) |
| /comment_automations/manage | page_comment_automation | Rules, subscriptions, aliases, webhook diagnostics |
| /tools/meta_tracking | meta_tracking | Pixel events, Custom Conversions, lead forms/leads |
| /tools/ga4 | google_analytics | GA4 properties, reports, funnels, realtime |
| /tools/website | website_intelligence | Tracking, landing pages, conversion analysis |
| /tools/journey | customer_journey | Meta+GA4 customer journey |
| /tools/clarity | clarity_analysis | Clarity summaries and behavior |
| /tools/reports | generate_report | PDF, Excel, DOCX, PPTX, HTML |
| /tools/dashboards | manage_dashboards | Dashboards and tenant datasets |
| /api/dashboard-runtime/v2/workflow | dashboard_runtime | Validate/preview/execute/publish section |
| /tools/intent | route_analysis_request | Natural-language intent dispatch |

## Important operational details

- Meta Graph API permissions, Page tasks, app review and selected tenant determine what works with real accounts.
- Webhook automation also needs Meta App webhook callback/subscriptions configured on the public application.
- No write operation should run unless the user approved exact payload and MCP_WRITES_ENABLED is set.
- The advanced editing adapter allows only approved method POST or DELETE, same as the original API.
- Existing REST endpoints and OpenAPI GPT Actions remain present; this does not deprecate them.
- Production deploy, OAuth compatibility for MCP clients, and live-account integration remain separate verification gates.
