# Definition-Driven Dashboard Engine

This project now supports two dashboard modes:

1. `dynamic_dashboards`
   Tenant-owned saved dashboard links with a flexible manifest, widgets, snapshots, and refresh planning.

2. `journey-dashboard/v7`
   A standalone Customer Journey dashboard runtime with dedicated APIs, chart rendering, stage inspector, trend studio, comparison lab, and fallback data.

## Add a Dashboard Definition

Create a definition:

```http
POST /api/dashboard-definitions
```

```json
{
  "dashboard_id": "customer_journey",
  "title": "Customer Journey Intelligence Dashboard",
  "filters": [
    {"key": "date_range", "type": "date_range", "applies_to": ["meta", "ga4", "clarity"]},
    {"key": "campaign_id", "type": "select", "source": "meta.campaigns", "optional": true}
  ],
  "data_sources": {
    "meta": {"connector": "meta_ads", "account_id": "act_123"},
    "ga4": {"connector": "ga4", "property_id": "529884683"},
    "clarity": {"connector": "clarity"}
  },
  "charts": [
    {"id": "conversion_path", "type": "conversion_path", "data_query": "journey_funnel"},
    {"id": "stage_inspector", "type": "stage_breakdown", "depends_on": "selected_stage"}
  ]
}
```

Run a definition query:

```http
POST /api/dashboard-runtime/query
```

```json
{
  "dashboard_id": "customer_journey",
  "query_id": "journey_funnel",
  "filters": {
    "date_from": "2026-06-15",
    "date_to": "2026-06-16",
    "campaign_id": "all"
  }
}
```

## Metric Sources

The metric dictionary lives in `app.analytics.dashboard_engine.METRIC_DICTIONARY`.

Important business rules:

- The first journey stage is `unique_ctr`, not impressions.
- Engagement comes from GA4 and Clarity, not Meta engagement metrics.
- `Register Page` is a Meta Event, not a Lead.
- OTP, Complete Profile, Start Trial, and CompleteRegistration are Meta Events.
- GA4 after Register is supporting data because source/medium can break after app transitions.

## Dedicated Journey APIs

- `GET /journey-dashboard/v7`
- `GET /api/journey/filters`
- `GET /api/journey/funnel`
- `GET /api/journey/stage-detail`
- `GET /api/journey/trend`
- `POST /api/journey/comparison`
- `GET /api/dashboard-runtime/connectors`

The current runtime includes fallback data so dashboards never render as blank while live connectors are being configured.
