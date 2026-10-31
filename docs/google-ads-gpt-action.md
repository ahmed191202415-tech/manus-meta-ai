# Google Ads bridge: existing GPT Actions schema (no reimport)

This integration is implemented behind the existing `POST /tools/intent` endpoint.
It does not add endpoints to `/openapi-gpt.json` and does not change request
fields or any existing Meta, GA4, Clarity or report actions.

## Authentication and setup

1. Connect the GPT Action to this application's existing OAuth service. The
   Google Ads bridge accepts ONLY a valid `app_...` bearer issued by that
   service and bound to a non-disabled tenant.
2. In the GPT Action, ask: `Google Ads connection status`. The server will
   return a short-lived `connect_url` if it needs Google authorization. Open
   that URL in a browser and consent to `https://www.googleapis.com/auth/adwords`.
   The existing GA4 scope is also requested.
3. In the same OAuth Google Cloud project, enable the Google Ads API and obtain
   **Explorer** (or higher) access for production accounts in the Google Cloud
   API Overview. Since September 9, 2026, new developer tokens are not
   required; any existing `GOOGLE_ADS_DEVELOPER_TOKEN` is optional.
4. In GPT, ask: `google ads list accounts`. Use the customer IDs returned.
   For linked client accounts, supply an optional `manager_id` (the
   ten-digit login-customer-id; never a user email).

## Existing JSON commands

The unchanged `IntentToolRequest.request` string can carry one JSON object
prefixed by `google_ads `. This avoids changing the GPT Action schema.

```text
google_ads {"action":"status"}
google_ads {"action":"list_accounts"}
google_ads {"action":"report","customer_id":"1234567890","report":"campaigns","date_range":"TODAY"}
google_ads {"action":"report","customer_id":"1234567890","report":"ad_groups","date_range":"LAST_7_DAYS"}
google_ads {"action":"report","customer_id":"1234567890","report":"keywords","date_range":"LAST_30_DAYS"}
google_ads {"action":"report","customer_id":"1234567890","report":"search_terms","date_range":"LAST_7_DAYS"}
google_ads {"action":"report","customer_id":"1234567890","report":"daily","date_range":"LAST_7_DAYS"}
google_ads {"action":"report","customer_id":"1234567890","report":"budgets"}
google_ads {"action":"query","customer_id":"1234567890","query":"SELECT campaign.id, campaign.name, campaign.status FROM campaign LIMIT 25"}
```

Available preset reports: campaigns, ad_groups, ads, keywords, search_terms,
budgets, daily, devices, conversions, negative_keywords.

The client may also pass natural Egyptian Arabic such as
`حلل إعلانات جوجل النهارده للحساب 123-456-7890`.
Calls without an account ID return the connected account list first.

## Writes: strictly preview then explicit confirmation

`prepare_mutation` uses Google Ads `validateOnly=true`. It **does not**
make account changes; the response includes the precise operations, a
short-lived approval token and a required confirmation phrase. Show all intended
changes to the user and obtain approval before `commit_mutation`.

```text
google_ads {"action":"prepare_mutation","customer_id":"1234567890","operations":[{"campaignOperation":{"update":{"resourceName":"customers/1234567890/campaigns/123","status":"PAUSED"},"updateMask":"status"}}]}
```

**Note:** Google Ads proto operation objects can have both `update` and
`updateMask`, which are fields inside a single campaignOperation. Always
build valid Google Ads operations and let validateOnly check before proposing.

To commit only after the human has approved this exact preview, include the
returned `approval_token`, `confirmation_phrase`, and action `commit_mutation`.
The approval expires within 10 minutes and can only be consumed once.

No real Google Ads account was modified during development. Generic mutations
are restricted to approved Google Ads resource-operation types; not every
Google Ads API feature is currently exposed. The hosting project must have
the necessary Google Cloud API access and the connected user must have
Google Ads permission to mutate the requested account.
