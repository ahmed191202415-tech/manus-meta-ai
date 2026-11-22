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
google_ads {"action":"report","customer_id":"1234567890","campaign_id":"123","report":"search_terms","start_date":"2026-11-16","end_date":"2026-11-22"}
google_ads {"action":"report","customer_id":"1234567890","report":"daily","date_range":"LAST_7_DAYS"}
google_ads {"action":"report","customer_id":"1234567890","report":"budgets"}
google_ads {"action":"query","customer_id":"1234567890","query":"SELECT campaign.id, campaign.name, campaign.status FROM campaign LIMIT 25"}
```

Available preset reports: campaigns, ad_groups, ads, keywords, search_terms,
budgets, daily, devices, conversions, negative_keywords.

The client may also pass natural Egyptian Arabic such as
`حلل إعلانات جوجل النهارده للحساب 123-456-7890`.
Calls without an account ID return the connected account list first.

Use `start_date` and `end_date` for an exact inclusive interval; `LAST_7_DAYS`
excludes today and is not a substitute for dates explicitly requested by the
user. `date` selects one calendar day. Report dates use the Google Ads
customer's time zone. Campaign/ad-group filters are applied to compatible
resources and rejected for incompatible configuration reports.

Reports include `period`, `scope`, `currency_code`, `time_zone`, `partial`,
`truncated`, `summary_scope`, and API provenance. Summaries cover returned rows.
Search Terms are Google's disclosed searches, not targeted keywords or the
entire campaign's spending total. Zero returned rows are an empty result, not
proof that there were no searches. Budget and conversion-action reports describe
configuration; the negative-keyword report currently covers ad-group negatives.

Explicit `query` commands accept only query execution inputs. Put campaign/date
filters inside GAQL; extra scope fields are rejected instead of ignored.
All reads are bounded, and an extra sentinel row detects truncation. An existing
GAQL LIMIT is never widened.

Structured errors preserve error family/code, field and Google request ID
across both Search and SearchStream. A provider `400` alone is not a permissions
diagnosis. Transient reads can be retried once; mutations are never replayed
automatically.

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
Consumption is one conditional database update, including for simultaneous
requests. `APPLIED` requires matching operation results. A transport failure
or incomplete mutation response means the outcome may be unknown: read the
affected resources before preparing another change.

## Deployment and verification

`requirements.txt` applies the committed `constraints.txt`, so a redeployment
uses the dependency versions tested by CI. Update that file deliberately and
run the full regression suite when upgrading dependencies.
Railpack's Python install step copies only recognized manifests by default.
The committed `railpack.json` adds `constraints.txt` to that step's inputs,
before pip runs; the later source-copy/build step would be too late.

`GET /health` exposes the deployed Git commit (when supplied by Railway/Vercel)
and the Google Ads report contract version. Check this after deployment, then
run the actual scoped read through the authenticated Action. Health and passing
mocked tests do not establish live Google Ads data access.

The architecture review and primary GitHub/Google references are documented in
[google-ads-reliability.md](google-ads-reliability.md).

No real Google Ads account was modified during development. Generic mutations
are restricted to approved Google Ads resource-operation types; not every
Google Ads API feature is currently exposed. The hosting project must have
the necessary Google Cloud API access and the connected user must have
Google Ads permission to mutate the requested account.
