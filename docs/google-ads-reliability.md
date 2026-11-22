# Google Ads reporting and mutation reliability

Reviewed against primary Google documentation and repository source on
2026-11-22. This document describes the implementation contract and the live
verification needed; passing local tests is not proof of production access.

## Diagnosis and error handling

HTTP 400 alone does not identify an authentication problem. Read the structured
Google Ads error family and symbolic code, field location, and request ID.
Ordinary REST Search responses are objects; SearchStream responses are arrays.
An error normalizer must handle both envelopes and preserve
`GoogleAdsFailure.errors`, `GoogleAdsFailure.requestId`, and
`google.rpc.ErrorInfo.reason` when available.

SDK protobuf `ListFields()` returns numeric enum values. Resolve those values
through the field's enum descriptor before producing a public error code;
stringifying the number loses the symbolic reason. Do not replace a known
provider code with an inference from an English message. Tokens, authorization
headers, query values, and raw error triggers do not belong in routine logs.

Primary references:

- [Google Ads error model](https://developers.google.com/google-ads/api/docs/best-practices/understand-api-errors)
- [REST Search and SearchStream](https://developers.google.com/google-ads/api/rest/common/search)
- [REST JSON mappings](https://developers.google.com/google-ads/api/rest/design/json-mappings)
- [Google API structured errors](https://google.aip.dev/193)
- [Protobuf enum and field descriptors](https://googleapis.dev/python/protobuf/latest/google/protobuf/descriptor.html)

## Report execution contract

`app/core/google_ads_reporting.py` separates pure query preparation from
authenticated transport and result validation. `prepare_report` returns a
query, normalized customer/manager identifiers, explicit scope, the requested
period, and read/display limits. The gateway executes this exact plan using
the authenticated tenant's saved Google connection, then calls
`finalize_report`.

- Preserve campaign and ad-group filters or reject an incompatible request.
  A campaign-scoped request must not silently become an account-wide report.
- Quote names as GAQL literals and validate numeric identifiers and calendar
  dates before sending any request.
- Use explicit inclusive dates for an explicitly requested interval. For
  example, 16–22 November 2026 means
  `segments.date BETWEEN '2026-11-16' AND '2026-11-22'`.
- `LAST_7_DAYS` excludes today; it cannot substitute for the interval above on
  22 November. Google evaluates periods using `customer.time_zone`.
- A single `date` retains the existing `date_range: "YYYY-MM-DD"` response
  contract. Explicit intervals also expose `start_date`, `end_date`, and
  `period.mode: "inclusive_range"`. Presets are returned as presets; unknown
  account time zones are not guessed.
- Budget, conversion-action configuration, and negative-keyword inventory
  reports reject date filters. Conversion-action definitions are not dated
  conversion performance.
- Historical metrics are not filtered by the entity's current enabled or
  removed status. Such filtering can discard valid historical activity.
- Fetch one extra row beyond the display limit to detect truncation, including
  at the maximum display size of 300. Do not count the extra row in summaries.
- Verify returned campaign/group IDs and names against requested scope and
  daily dates against the explicit interval. Reject inconsistent account
  metadata.
- Currency and time zone come from selected customer fields, not a configured
  default. Empty results keep these values unknown.
- Every aggregate is explicitly scoped to `returned_rows`. Truncation marks
  it partial; a row-limited aggregate is not a full account total.

Relevant field and period references:

- [Search-term fields and compatible resources](https://developers.google.com/google-ads/api/fields/v25/search_term_view)
- [Campaign fields](https://developers.google.com/google-ads/api/fields/v25/campaign)
- [Ad-group fields](https://developers.google.com/google-ads/api/fields/v25/ad_group)
- [Ad fields](https://developers.google.com/google-ads/api/fields/v25/ad_group_ad)
- [Keyword performance fields](https://developers.google.com/google-ads/api/fields/v25/keyword_view)
- [Date ranges and account time zones](https://developers.google.com/google-ads/api/docs/query/date-ranges)

### Search terms and negative keywords

`search_terms` uses `search_term_view.search_term`, not targeted keyword text.
Its rows are aggregated by search term and ad group. Google can omit terms due
to disclosure thresholds, so even an untruncated search-term report is not a
complete campaign spending total. `search_term_view` excludes Performance Max;
its campaign search-term resource must be used separately when applicable.

The existing `negative_keywords` report covers ad-group keyword criteria only.
Its response discloses that scope; campaign negatives, account negatives, and
shared-list negatives are separate resources.

- [Search-term disclosure and reconciliation](https://developers.google.com/google-ads/api/docs/campaigns/ai-max-for-search-campaigns/ai-max-reporting)

## SDK, API versions, and access

Do not infer that a supported API version is the cause of a 400 response. On
the review date v25 is supported until August 2027 and v26 until November 2027.
Pin versions and check Google's published sunset table before upgrading.

Developer tokens were sunset on 9 September 2026. The optional legacy header
is ignored; access is determined by the Cloud project owning the OAuth
credentials. Some older REST page summaries still describe the previous
token requirement. Prefer the current migration guide and avoid adding a
dummy token or requiring a new one.

- [API versions and supported SDK versions](https://developers.google.com/google-ads/api/docs/sunset-dates)
- [Developer-token migration](https://developers.google.com/google-ads/api/docs/api-policy/developer-token)
- [Python SDK changelog](https://github.com/googleads/google-ads-python/blob/main/ChangeLog)

## Mutation contract

Keep the application's tenant-bound, expiring, single-use approval flow.
Validate the exact operation payload with `validateOnly: true` before issuing
a proposal. Bind confirmation to customer, manager, tenant, and exact
operations. Use explicit field masks for updates.

The default atomic mode (`partialFailure: false`) is appropriate for dependent
operations. If partial failure is enabled for independent operations, inspect
operation-level failures even on HTTP success and report exactly what changed.
An ambiguous transport failure after a commit attempt must not trigger a blind
write retry; preserve the attempt state and reconcile the account first.

- [Mutation operations and field masks](https://developers.google.com/google-ads/api/docs/concepts/changing-objects)
- [Validation and bulk mutations](https://developers.google.com/google-ads/api/docs/mutating/bulk-mutate)
- [Partial failure semantics](https://developers.google.com/google-ads/api/docs/best-practices/partial-failures)

## Open-source projects reviewed

| Project | Patterns used as reference | Scope |
| --- | --- | --- |
| [googleads/google-ads-python](https://github.com/googleads/google-ads-python) | Typed client, structured exceptions, field masks, partial-failure decoding | Official Python client |
| [googleads/google-ads-mcp](https://github.com/googleads/google-ads-mcp) | Structured query inputs, resource metadata, scoped identifiers, validated proposal/confirmation | Official repository; selected mutation tools |
| [google/ads-api-report-fetcher](https://github.com/google/ads-api-report-fetcher) | Separate query execution and report output, account/report orchestration | Google-owned repository; explicitly not an officially supported product |

Specific MCP source reviewed: `ads_mcp/tools/search.py`,
`ads_mcp/tools/get_resource_metadata.py`, and `ads_mcp/propose_and_confirm.py`.
The MCP checksum demonstrates payload consistency; a publicly computable
checksum alone is not a replacement for this application's authenticated,
server-tracked approval and replay prevention.

## Release verification

Regression tests must cover the exact SMS campaign/date request, raw GAQL
preservation, routing precedence, both REST error envelopes, real SDK enum
decoding, scope mismatch, limits and partial summaries, tenant isolation, and
single-use mutation confirmation. The reporting-specific cases are in
`tests/test_google_ads_report_regressions.py`.

After deployment, verify the deployed commit and run a read for the requested
customer/campaign/period. Record source, method, actual date range, row count,
truncation, currency/time zone when returned, and the provider request ID on
failure. A successful OAuth callback, accessible-customer list, or configuration
query does not establish that a specific performance query succeeded. Never
label mocked test values or configuration rows as actual campaign results.
