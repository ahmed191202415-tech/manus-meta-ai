# Universal Dashboard Runtime v2

The runtime lets ChatGPT create the backend of any dashboard section without adding a dedicated API endpoint for every request.

## Required workflow

ChatGPT must use `POST /api/dashboard-runtime/v2/workflow` in this order:

1. `capabilities`: inspect supported connectors and operations.
2. `validate`: validate the declarative query graph without fetching data.
3. `preview`: fetch live data and show values, sources, filters, and errors in chat.
4. Wait for the user's explicit confirmation.
5. `publish_section`: publish the exact previewed plan using its short-lived `confirmation_token`.

Publishing a changed, expired, or unpreviewed plan is rejected.

## Plan model

Each plan is a dependency graph of safe nodes. A node selects a connector, operation, parameters, required inputs, dependencies, and trigger. Parameters may reference dashboard inputs and earlier results:

```json
{
  "id": "campaign_selector",
  "nodes": [
    {
      "id": "campaigns",
      "connector": "meta",
      "operation": "list_campaigns",
      "params": {"account_id": "{{inputs.account_id}}"},
      "required_inputs": ["account_id"],
      "run_when": "on_change"
    },
    {
      "id": "options",
      "connector": "transform",
      "operation": "options",
      "params": {"from": "campaigns", "label_field": "name", "value_field": "id"},
      "depends_on": ["campaigns"],
      "run_when": "on_change"
    }
  ],
  "output": {"options": "{{nodes.options}}"}
}
```

The same model supports filters, KPIs, funnels, charts, tables, comparisons, and alerts. A funnel can combine Meta insights, GA4 reports, Clarity insights, and safe transform nodes in one plan.

## Supported connectors

- Meta: accounts, campaigns, ad sets, ads, insights, and safe Graph reads.
- GA4: properties, arbitrary reports, and funnels.
- Clarity: live insights.
- Transform: nested selection, label/value options, and safe numeric formulas.

The runtime never executes generated Python, JavaScript, shell commands, or arbitrary network URLs. ChatGPT composes only registered operations.

## Live execution

Published plans are stored under the dashboard's `runtime_queries`. Existing dashboard pages can execute them through either:

- `POST /api/dashboard-runtime/query` with the dashboard and query IDs.
- `POST /api/dashboard-runtime/v2/{dashboard_id}/queries/{query_id}`.

Dashboard inputs such as account, campaign, ad set, ad, date range, device, or any future field are passed in `inputs`/`filters` and resolved at execution time. The saved backend contains query definitions, not fixed metric snapshots.
