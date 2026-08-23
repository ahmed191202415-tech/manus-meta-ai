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

## Funnel data contract

Funnels use the generic `transform.funnel` operation; they do not require a new HTTP endpoint for each dashboard request. Each stage declares a live metric reference and its real source. The transform returns a standard contract containing:

- `numeric_value` and `source_status` for the stage count.
- `cost`, `transition_rate`, and `drop_rate` calculated from the live preview.
- Optional `revenue` and `roas` for revenue stages.
- Optional `details` for supporting engagement signals such as time and scroll.
- `complete=false` plus `missing_sources` when an event or metric has not been mapped.

A funnel publication is rejected unless all of the following are true:

1. The plan output explicitly maps `stages`, `complete`, and `status`.
2. The presentation contains at least two ordered stage definitions with `id`, `label`, and `source`.
3. The signed live preview contains the stage rows and reports `complete=true`.
4. The confirmed plan is identical to the previewed plan.

`sign_up_ref` is an attribution dimension, not an event or a funnel stage. It may be requested as a GA4 dimension or breakdown, but the publication validator rejects it when bound to `event_name`.

The Customer Journey section should be mapped only after event discovery and live preview. Its intended business sequence is external link clicks, landing arrival, landing engagement (with time/scroll as details), Register Page, OTP, Complete Profile, and Purchase. Purchase may expose revenue and ROAS when the connected source returns them. No demonstration metrics are allowed in a published section.

## Live execution

Published plans are stored under the dashboard's `runtime_queries`. Existing dashboard pages can execute them through either:

- `POST /api/dashboard-runtime/query` with the dashboard and query IDs.
- `POST /api/dashboard-runtime/v2/{dashboard_id}/queries/{query_id}`.

Dashboard inputs such as account, campaign, ad set, ad, date range, device, or any future field are passed in `inputs`/`filters` and resolved at execution time. The saved backend contains query definitions, not fixed metric snapshots.
