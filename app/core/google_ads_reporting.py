"""Validated, tenant-neutral Google Ads report plans and result contracts.

This module performs no network or credential access. A caller executes the
exact plan using its authenticated tenant connection, then finalizes the rows.
Resources/fields are based on the Google Ads v25/v26 reporting reference; see
docs/google-ads-reliability.md for the primary sources and reporting semantics.
"""
from __future__ import annotations

from datetime import date as calendar_date
from decimal import Decimal, InvalidOperation
import re
from typing import Callable

from fastapi import HTTPException

MAX_REPORT_ROWS = 300
DURATIONS = frozenset({
    "TODAY", "YESTERDAY", "LAST_7_DAYS", "LAST_14_DAYS", "LAST_30_DAYS",
    "THIS_MONTH", "LAST_MONTH", "LAST_BUSINESS_WEEK", "THIS_WEEK_SUN_TODAY",
    "THIS_WEEK_MON_TODAY", "LAST_WEEK_SUN_SAT", "LAST_WEEK_MON_SUN",
})
_ACCOUNT = "customer.id, customer.currency_code, customer.time_zone"
_CAMPAIGN = "campaign.id, campaign.name"
_GROUP = "ad_group.id, ad_group.name"
_METRICS = (
    "metrics.cost_micros, metrics.impressions, metrics.clicks,"
    " metrics.conversions, metrics.conversions_value, metrics.ctr, metrics.average_cpc"
)
# Keep the public report names and the (fields, resource) shape stable.
REPORTS = {
    "campaigns": (
        f"{_ACCOUNT}, {_CAMPAIGN}, campaign.status, campaign.advertising_channel_type,"
        f" campaign.campaign_budget, {_METRICS}", "campaign"),
    "ad_groups": (
        f"{_ACCOUNT}, {_CAMPAIGN}, {_GROUP}, ad_group.status, {_METRICS}", "ad_group"),
    "ads": (
        f"{_ACCOUNT}, {_CAMPAIGN}, {_GROUP}, ad_group_ad.ad.id, ad_group_ad.ad.name,"
        f" ad_group_ad.status, {_METRICS}", "ad_group_ad"),
    "keywords": (
        f"{_ACCOUNT}, {_CAMPAIGN}, {_GROUP}, ad_group_criterion.criterion_id,"
        " ad_group_criterion.keyword.text, ad_group_criterion.keyword.match_type,"
        " ad_group_criterion.status, ad_group_criterion.quality_info.quality_score,"
        f" {_METRICS}", "keyword_view"),
    "search_terms": (
        f"{_ACCOUNT}, {_CAMPAIGN}, {_GROUP}, search_term_view.search_term,"
        f" search_term_view.status, {_METRICS}", "search_term_view"),
    "budgets": (
        "campaign_budget.id, campaign_budget.name, campaign_budget.amount_micros,"
        " campaign_budget.status, campaign_budget.delivery_method", "campaign_budget"),
    "daily": (
        f"{_ACCOUNT}, {_CAMPAIGN}, segments.date, {_METRICS}", "campaign"),
    "devices": (
        f"{_ACCOUNT}, {_CAMPAIGN}, segments.device, {_METRICS}", "campaign"),
    "conversions": (
        "conversion_action.id, conversion_action.name, conversion_action.type,"
        " conversion_action.status, conversion_action.category", "conversion_action"),
    "negative_keywords": (
        f"{_CAMPAIGN}, {_GROUP}, ad_group_criterion.criterion_id,"
        " ad_group_criterion.keyword.text, ad_group_criterion.keyword.match_type,"
        " ad_group_criterion.negative", "ad_group_criterion"),
}
PERFORMANCE_REPORTS = frozenset({
    "campaigns", "ad_groups", "ads", "keywords", "search_terms", "daily", "devices",
})
_GROUP_REPORTS = frozenset({"ad_groups", "ads", "keywords", "search_terms", "negative_keywords"})
_CAMPAIGN_REPORTS = PERFORMANCE_REPORTS | {"negative_keywords"}
_REPORT_ALIASES = {
    "campaign": "campaigns", "ad_group": "ad_groups", "ad_group_ad": "ads",
    "keyword_view": "keywords", "search_term_view": "search_terms",
    "search_term": "search_terms", "conversion_actions": "conversions",
}
_ALLOWED_ARGUMENTS = frozenset({
    "action", "provider", "report", "customer_id", "manager_id", "login_customer_id",
    "campaign_id", "campaign_name", "ad_group_id", "ad_group_name", "date",
    "start_date", "end_date", "date_range", "limit", "search_stream",
})


def _invalid(message: str) -> None:
    raise HTTPException(422, message)


def _id(value: object, field: str, *, customer: bool = False) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        _invalid(f"{field} must be a numeric identifier.")
    text = str(value).strip()
    if customer:
        text = text.replace("-", "")
    pattern = r"[0-9]{10}" if customer else r"[1-9][0-9]{0,18}"
    if not re.fullmatch(pattern, text):
        _invalid(f"{field} must be {'ten digits' if customer else 'a positive numeric identifier'}.")
    return text


def _name(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 255:
        _invalid(f"{field} must be a non-empty name of at most 255 characters.")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        _invalid(f"{field} cannot contain control characters.")
    return value


def _literal(value: str) -> str:
    # GAQL accepts backslash escapes for backslashes and quote delimiters.
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _date(value: object, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        _invalid(f"{field} must be YYYY-MM-DD.")
    try:
        calendar_date.fromisoformat(value)
    except ValueError:
        _invalid(f"{field} is not a valid calendar date.")
    return value


def _provided(args: dict, field: str) -> bool:
    return field in args and args[field] is not None and args[field] != ""


def prepare_report(args: dict) -> dict:
    """Build a scoped read plan; reject unsupported scope instead of ignoring it."""
    if not isinstance(args, dict):
        _invalid("Google Ads report arguments must be an object.")
    unsupported = [key for key in args if key not in _ALLOWED_ARGUMENTS and _provided(args, key)]
    if unsupported:
        _invalid("Unsupported report arguments: " + ", ".join(sorted(unsupported)) + ". Use an explicit GAQL query for other filters.")
    report = str(args.get("report") or "campaigns").strip().lower()
    report = _REPORT_ALIASES.get(report, report)
    if report not in REPORTS:
        _invalid("Unknown report. Use: " + ", ".join(REPORTS))
    customer_id = _id(args.get("customer_id"), "customer_id", customer=True)
    manager_ids = [_id(args[key], key, customer=True) for key in ("manager_id", "login_customer_id") if _provided(args, key)]
    if len(set(manager_ids)) > 1:
        _invalid("manager_id and login_customer_id disagree.")
    manager_id = manager_ids[0] if manager_ids else None
    scope = {"customer_id": customer_id}
    conditions = []
    performance = report in PERFORMANCE_REPORTS

    has_date = _provided(args, "date")
    has_start = _provided(args, "start_date")
    has_end = _provided(args, "end_date")
    if has_date and (has_start or has_end):
        _invalid("Use either date or start_date/end_date, not both.")
    if has_start != has_end:
        _invalid("Supply both start_date and end_date for an inclusive date range.")
    if not performance and any(_provided(args, key) for key in ("date", "start_date", "end_date", "date_range")):
        _invalid("This configuration report does not support date filters. Request a performance report for dated metrics.")

    requested_date = start_date = end_date = date_range = None
    period_mode = "not_applicable"
    if has_date:
        requested_date = _date(args["date"], "date")
        start_date = end_date = requested_date
        date_range = requested_date
        period_mode = "date"
        conditions.append(f"segments.date = '{requested_date}'")
    elif has_start:
        start_date, end_date = _date(args["start_date"], "start_date"), _date(args["end_date"], "end_date")
        if start_date > end_date:
            _invalid("start_date must not be after end_date.")
        date_range = f"{start_date}..{end_date}"
        period_mode = "inclusive_range"
        conditions.append(f"segments.date BETWEEN '{start_date}' AND '{end_date}'")
    elif performance:
        date_range = str(args.get("date_range") or "LAST_7_DAYS").upper()
        if date_range not in DURATIONS:
            _invalid("Unsupported Google Ads date_range. Use a supported DURING period or explicit start_date/end_date; ALL_TIME is not supported for performance reports.")
        period_mode = "preset"
        conditions.append(f"segments.date DURING {date_range}")

    for field, gaql, allowed in (
        ("campaign_id", "campaign.id", _CAMPAIGN_REPORTS),
        ("campaign_name", "campaign.name", _CAMPAIGN_REPORTS),
        ("ad_group_id", "ad_group.id", _GROUP_REPORTS),
        ("ad_group_name", "ad_group.name", _GROUP_REPORTS),
    ):
        if not _provided(args, field):
            continue
        if report not in allowed:
            _invalid(f"{report} does not support {field}; choose a compatible report or use an explicit GAQL query.")
        value = _id(args[field], field) if field.endswith("_id") else _name(args[field], field)
        scope[field] = value
        conditions.append(f"{gaql} = {value if field.endswith('_id') else _literal(value)}")
    if report == "negative_keywords":
        conditions.extend(("ad_group_criterion.negative = TRUE", "ad_group_criterion.type = 'KEYWORD'"))
        scope["negative_keyword_level"] = "ad_group"

    raw_limit = args.get("limit", 100)
    if isinstance(raw_limit, bool) or not isinstance(raw_limit, (int, str)) or not re.fullmatch(r"[0-9]+", str(raw_limit)) or int(raw_limit) < 1:
        _invalid("limit must be a positive integer.")
    display_limit = min(int(raw_limit), MAX_REPORT_ROWS)
    if "search_stream" in args and not isinstance(args["search_stream"], bool):
        _invalid("search_stream must be a boolean.")
    fields, resource = REPORTS[report]
    query = f"SELECT {fields} FROM {resource}"
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    if performance:
        query += " ORDER BY " + ("segments.date ASC, " if report == "daily" else "") + "metrics.cost_micros DESC"
    # One extra result distinguishes a complete report from a full-sized page.
    read_limit = display_limit + 1
    query += f" LIMIT {read_limit}"
    return {
        "query": query, "customer_id": customer_id, "manager_id": manager_id,
        "report": report, "resource": resource, "scope": scope,
        "performance": performance, "display_limit": display_limit, "read_limit": read_limit,
        "search_stream": bool(has_date or has_start or args.get("search_stream")),
        "date": requested_date, "date_range": date_range,
        "start_date": start_date, "end_date": end_date, "period_mode": period_mode,
    }


def _bad_response(message: str) -> None:
    raise HTTPException(502, {
        "origin": "google_ads_response", "code": "GOOGLE_ADS_REPORT_SCOPE_MISMATCH",
        "message": message, "next_step": "Inspect the report adapter response; do not present these rows as the requested report.",
    })


def _entity(row: dict, camel: str, snake: str | None = None) -> dict:
    value = row.get(camel, row.get(snake, {}) if snake else {})
    if not isinstance(value, dict):
        _bad_response("Google Ads returned a malformed report resource.")
    return value


def _require_result_id(entity: dict, field: str = "id") -> None:
    value = entity.get(field)
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not re.fullmatch(r"[1-9][0-9]{0,18}", str(value)):
        _bad_response("Google Ads report is missing a selected resource identifier.")


def _validate_report_resource(report: str, row: dict, entities: dict) -> None:
    """Configuration rows cannot masquerade as a different report resource."""
    if report in _CAMPAIGN_REPORTS:
        _require_result_id(entities["campaign"])
    if report in _GROUP_REPORTS:
        _require_result_id(entities["ad_group"])
    if report == "search_terms":
        terms = _entity(row, "searchTermView", "search_term_view")
        term = terms.get("searchTerm", terms.get("search_term"))
        if not isinstance(term, str) or not term:
            _bad_response("Google Ads did not return actual search-term text for the search_terms report.")
    elif report in {"keywords", "negative_keywords"}:
        criterion = _entity(row, "adGroupCriterion", "ad_group_criterion")
        _require_result_id(criterion, "criterionId" if "criterionId" in criterion else "criterion_id")
        keyword = _entity(criterion, "keyword")
        if not isinstance(keyword.get("text"), str) or not keyword["text"]:
            _bad_response("Google Ads did not return keyword text for the requested keyword report.")
        if report == "negative_keywords" and criterion.get("negative") is not True:
            _bad_response("Google Ads returned a non-negative keyword in a negative-keyword report.")
    elif report == "ads":
        _require_result_id(_entity(_entity(row, "adGroupAd", "ad_group_ad"), "ad"))
    elif report == "budgets":
        _require_result_id(_entity(row, "campaignBudget", "campaign_budget"))
    elif report == "conversions":
        _require_result_id(_entity(row, "conversionAction", "conversion_action"))
    elif report == "devices":
        device = _entity(row, "segments").get("device")
        if not isinstance(device, str) or not device:
            _bad_response("Google Ads device report is missing the selected device segment.")


def aggregate_metrics(rows: list[dict]) -> dict:
    """Aggregate only returned rows, without silently swallowing malformed metrics."""
    totals = {key: Decimal(0) for key in ("costMicros", "clicks", "impressions", "conversions", "conversionsValue")}
    for row in rows:
        metrics = _entity(row, "metrics")
        for key in totals:
            snake = re.sub(r"[A-Z]", lambda m: "_" + m.group().lower(), key)
            raw = metrics.get(key, metrics.get(snake, 0))
            try:
                value = Decimal(str(raw))
            except (InvalidOperation, ValueError, TypeError):
                _bad_response("Google Ads returned non-numeric report metrics.")
            if not value.is_finite() or (key in {"costMicros", "clicks", "impressions"} and value != value.to_integral_value()):
                _bad_response("Google Ads returned invalid numeric report metrics.")
            if key in {"clicks", "impressions"} and value < 0:
                _bad_response("Google Ads returned a negative click or impression count.")
            totals[key] += value
    spend = totals["costMicros"] / Decimal(1_000_000)
    clicks, impressions = int(totals["clicks"]), int(totals["impressions"])
    conversions, value = totals["conversions"], totals["conversionsValue"]
    return {
        "cost": str(spend), "clicks": clicks, "impressions": impressions,
        "conversions": str(conversions), "conversion_value": str(value),
        "ctr_percent": round(clicks * 100 / impressions, 3) if impressions else None,
        "cpc": str(round(spend / clicks, 2)) if clicks else None,
        "cost_per_conversion": str(round(spend / conversions, 2)) if conversions else None,
        "roas": str(round(value / spend, 2)) if spend else None,
        "note": "Cost uses the selected account currency. Conversions reflect Google Ads attribution, not verified CRM sales.",
    }


def finalize_report(plan: dict, result: dict, *, aggregate: Callable | None = None, api_version: str | None = None) -> dict:
    """Check the result scope and disclose coverage before returning a report."""
    if not isinstance(result, dict) or not isinstance(result.get("rows"), list) or result.get("ok") is False or "error" in result or "partialFailureError" in result:
        _bad_response("Google Ads did not return a successful report result.")
    rows = result["rows"]
    currencies, time_zones = set(), set()
    for row in rows:
        if not isinstance(row, dict):
            _bad_response("Google Ads returned malformed report rows.")
        entities = {"customer": _entity(row, "customer"), "campaign": _entity(row, "campaign"), "ad_group": _entity(row, "adGroup", "ad_group")}
        _validate_report_resource(plan["report"], row, entities)
        customer = entities["customer"]
        if customer.get("id") is not None and str(customer["id"]) != plan["customer_id"]:
            _bad_response("Google Ads report rows do not match the requested customer.")
        for field in ("campaign_id", "campaign_name", "ad_group_id", "ad_group_name"):
            if field in plan["scope"]:
                entity_name, attribute = field.rsplit("_", 1)
                if str(entities[entity_name].get(attribute, "")) != plan["scope"][field]:
                    _bad_response("Google Ads report rows do not match the requested campaign or ad group.")
        if plan["report"] == "daily":
            row_date = _entity(row, "segments").get("date")
            try:
                _date(row_date, "segments.date")
            except HTTPException:
                _bad_response("Google Ads daily report returned an invalid or missing date.")
            if plan["start_date"] and not plan["start_date"] <= row_date <= plan["end_date"]:
                _bad_response("Google Ads daily report rows are outside the requested dates.")
        currency = customer.get("currencyCode", customer.get("currency_code"))
        time_zone = customer.get("timeZone", customer.get("time_zone"))
        if isinstance(currency, str) and currency:
            currencies.add(currency)
        if isinstance(time_zone, str) and time_zone:
            time_zones.add(time_zone)
    if len(currencies) > 1 or len(time_zones) > 1:
        _bad_response("Google Ads returned inconsistent customer currency or time zone.")
    truncated = bool(result.get("truncated")) or len(rows) > plan["display_limit"]
    shown_rows = rows[:plan["display_limit"]]
    search_terms = plan["report"] == "search_terms"
    partial = truncated or search_terms
    response = {
        **result, "rows": shown_rows, "count": len(shown_rows), "truncated": truncated,
        "customer_id": plan["customer_id"], "report": plan["report"], "resource": plan["resource"],
        "scope": dict(plan["scope"]), "gaql": plan["query"], "date_range": plan["date_range"],
        "start_date": plan["start_date"], "end_date": plan["end_date"],
        "period": {"mode": plan["period_mode"], "start_date": plan["start_date"], "end_date": plan["end_date"], "preset": plan["date_range"] if plan["period_mode"] == "preset" else None, "time_zone_basis": "customer.time_zone"},
        "currency_code": next(iter(currencies), None), "time_zone": next(iter(time_zones), None),
        "summary_scope": "returned_rows", "partial": partial, "empty": not shown_rows,
        "data_source": "google_ads_api", "verified_by_google_api": True, "google_api_called": True,
        "query_method": result.get("query_method") or ("GoogleAdsService.SearchStream" if plan["search_stream"] else "GoogleAdsService.Search"),
    }
    if api_version is not None:
        response["api_version"] = api_version
    if search_terms:
        response["coverage_note"] = "Returned search terms are the terms disclosed by Google Ads, aggregated by ad group. Their totals are not full campaign totals; this resource excludes Performance Max."
    elif plan["report"] == "negative_keywords":
        response["coverage_note"] = "Ad-group negative keywords only; campaign, account, and shared-list negatives are separate resources."
    elif not plan["performance"]:
        response["coverage_note"] = "Current configuration; no performance date range or attributed conversion totals."
    if truncated:
        response["truncation_note"] = "The row limit was reached. Summaries cover only the returned rows."
    if plan["performance"]:
        response["summary"] = (aggregate or aggregate_metrics)(shown_rows)
        response["summary"].update({"scope": "returned_rows", "partial": partial, "currency_code": response["currency_code"]})
    return response
