"""Report contracts for the user's SMS campaign and bounded result handling."""
from copy import deepcopy

from fastapi import HTTPException
import pytest

from app.core.google_ads_reporting import (
    REPORTS, aggregate_metrics, finalize_report, prepare_report,
)


def sms_args(**changes):
    return {
        "action": "report", "customer_id": "3333735582", "report": "search_terms",
        "campaign_id": "24445941074", "campaign_name": "sms حملة",
        "start_date": "2026-11-16", "end_date": "2026-11-22", **changes,
    }


def sms_row(**changes):
    return {
        "customer": {"id": "3333735582", "currencyCode": "EGP", "timeZone": "Africa/Cairo"},
        "campaign": {"id": "24445941074", "name": "sms حملة"},
        "adGroup": {"id": "123456789", "name": "SMS services"},
        "searchTermView": {"searchTerm": "رسائل sms للشركات"},
        "metrics": {"costMicros": "2400000", "impressions": "30", "clicks": "4", "conversions": "0.5", "conversionsValue": "12"},
        **changes,
    }


def test_sms_terms_use_campaign_filter_and_full_inclusive_interval():
    plan = prepare_report(sms_args())
    query = plan["query"]
    assert "FROM search_term_view" in query
    assert "campaign.id = 24445941074" in query
    assert "campaign.name = 'sms حملة'" in query
    assert "segments.date BETWEEN '2026-11-16' AND '2026-11-22'" in query
    assert "metrics.conversions_value" in query
    assert "campaign.id," in query and "ad_group.id," in query
    assert "ORDER BY metrics.cost_micros DESC LIMIT 101" in query
    assert "DURING LAST_7_DAYS" not in query
    assert "campaign.status =" not in query
    assert plan["start_date"] == "2026-11-16"
    assert plan["end_date"] == "2026-11-22"
    assert plan["search_stream"] is True


def test_resource_report_alias_and_hyphenated_customer_manager_are_supported():
    plan = prepare_report(sms_args(report="search_term_view", customer_id="333-373-5582", manager_id="111-222-3333"))
    assert plan["report"] == "search_terms"
    assert plan["customer_id"] == "3333735582"
    assert plan["manager_id"] == "1112223333"


def test_named_scope_escapes_backslashes_and_quotes_without_changing_name():
    name = "SMS \\ sale's حملة"
    plan = prepare_report(sms_args(campaign_name=name))
    assert "campaign.name = 'SMS \\\\ sale\\'s حملة'" in plan["query"]
    assert plan["scope"]["campaign_name"] == name


@pytest.mark.parametrize("changes", [
    {"start_date": "2026-02-30"}, {"end_date": "2026-13-22"},
    {"start_date": "2026-11-16' OR 1=1"}, {"start_date": "2026-11-23"},
    {"end_date": None}, {"date": "2026-11-22"},
    {"campaign_id": "24445941074 OR 1=1"}, {"campaign_id": True},
    {"customer_id": "3333735582/../other"}, {"manager_id": "bad"},
    {"campaign_name": "sms\nSELECT"}, {"campaign_name": "   "},
    {"limit": 0}, {"limit": -1}, {"limit": 1.5}, {"limit": True},
    {"search_stream": "false"}, {"filters": {"campaign.id": "another"}},
    {"campaign_ids": ["24445941074"]},
])
def test_invalid_or_unsupported_inputs_fail_before_any_network_call(changes):
    with pytest.raises(HTTPException) as exc:
        prepare_report(sms_args(**changes))
    assert exc.value.status_code == 422


def test_manager_alias_conflict_is_rejected():
    with pytest.raises(HTTPException) as exc:
        prepare_report(sms_args(manager_id="1112223333", login_customer_id="4445556666"))
    assert exc.value.status_code == 422


@pytest.mark.parametrize("report,filter_args", [
    ("budgets", {"campaign_id": "24445941074"}),
    ("conversions", {"campaign_name": "sms حملة"}),
    ("campaigns", {"ad_group_id": "123456789"}),
    ("daily", {"ad_group_name": "SMS services"}),
    ("devices", {"ad_group_id": "123456789"}),
])
def test_incompatible_resource_scope_is_not_silently_ignored(report, filter_args):
    with pytest.raises(HTTPException) as exc:
        prepare_report({"customer_id": "3333735582", "report": report, **filter_args})
    assert exc.value.status_code == 422


@pytest.mark.parametrize("report", ["budgets", "conversions", "negative_keywords"])
@pytest.mark.parametrize("dates", [{"date": "2026-11-22"}, {"start_date": "2026-11-16", "end_date": "2026-11-22"}, {"date_range": "TODAY"}])
def test_configuration_reports_reject_dates_instead_of_claiming_dated_results(report, dates):
    with pytest.raises(HTTPException) as exc:
        prepare_report({"customer_id": "3333735582", "report": report, **dates})
    assert exc.value.status_code == 422


def test_negative_keywords_report_discloses_ad_group_scope_and_selects_only_keywords():
    plan = prepare_report({"customer_id": "3333735582", "report": "negative_keywords", "campaign_id": "24445941074"})
    assert "ad_group_criterion.negative = TRUE" in plan["query"]
    assert "ad_group_criterion.type = 'KEYWORD'" in plan["query"]
    assert "segments.date" not in plan["query"]
    assert plan["scope"]["negative_keyword_level"] == "ad_group"
    result = finalize_report(plan, {"rows": []})
    assert "summary" not in result
    assert result["date_range"] is None
    assert "Ad-group" in result["coverage_note"]


def test_single_date_keeps_contract_even_with_legacy_parser_default():
    plan = prepare_report({"customer_id": "3333735582", "date": "2026-11-22", "date_range": "LAST_7_DAYS"})
    assert "WHERE segments.date = '2026-11-22'" in plan["query"]
    assert plan["date_range"] == "2026-11-22"
    assert plan["search_stream"] is True


def test_last_seven_days_is_preserved_as_a_preset_not_invented_explicit_dates():
    plan = prepare_report({"customer_id": "3333735582", "date_range": "LAST_7_DAYS"})
    result = finalize_report(plan, {"rows": []})
    assert "segments.date DURING LAST_7_DAYS" in plan["query"]
    assert result["period"]["preset"] == "LAST_7_DAYS"
    assert result["start_date"] is None and result["end_date"] is None
    assert result["currency_code"] is None and result["time_zone"] is None


def test_all_time_is_not_silently_treated_as_a_bounded_performance_period():
    with pytest.raises(HTTPException) as exc:
        prepare_report({"customer_id": "3333735582", "date_range": "ALL_TIME"})
    assert exc.value.status_code == 422


def test_result_uses_disclosed_terms_and_provided_account_metadata():
    plan = prepare_report(sms_args())
    result = finalize_report(plan, {"rows": [sms_row()]}, api_version="v25")
    assert result["summary"]["cost"] == "2.4"
    assert result["summary"]["conversions"] == "0.5"
    assert result["summary"]["conversion_value"] == "12"
    assert result["summary"]["cost_per_conversion"] == "4.80"
    assert result["summary_scope"] == "returned_rows"
    assert result["partial"] is True and result["truncated"] is False
    assert result["currency_code"] == "EGP" and result["time_zone"] == "Africa/Cairo"
    assert result["verified_by_google_api"] is True
    assert result["query_method"] == "GoogleAdsService.SearchStream"
    assert result["api_version"] == "v25"
    assert "not full campaign totals" in result["coverage_note"]


def test_sentinel_marks_truncation_but_is_not_included_in_summary():
    plan = prepare_report(sms_args(limit=1))
    original = {"rows": [sms_row(), sms_row(metrics={"costMicros": "999999999", "clicks": "100"})], "truncated": False}
    result = finalize_report(plan, original)
    assert plan["read_limit"] == 2
    assert result["count"] == 1 and result["truncated"] is True
    assert result["summary"]["clicks"] == 4
    assert result["summary"]["cost"] == "2.4"
    assert len(original["rows"]) == 2


def test_full_sized_complete_report_is_not_automatically_marked_truncated():
    plan = prepare_report({"customer_id": "3333735582", "date": "2026-11-22", "limit": 1})
    result = finalize_report(plan, {"rows": [sms_row()], "truncated": False})
    assert result["count"] == 1 and result["truncated"] is False
    assert result["partial"] is False


def test_display_cap_retains_one_extra_read_for_truncation_detection():
    plan = prepare_report(sms_args(limit=999))
    assert plan["display_limit"] == 300
    assert plan["read_limit"] == 301
    assert plan["query"].endswith("LIMIT 301")


@pytest.mark.parametrize("changes", [
    {"campaign": {"id": "999999999", "name": "sms حملة"}},
    {"campaign": {"id": "24445941074", "name": "Another campaign"}},
    {"campaign": {}},
    {"customer": {"id": "0000000000"}},
])
def test_wrong_or_missing_requested_scope_is_never_returned_as_success(changes):
    with pytest.raises(HTTPException) as exc:
        finalize_report(prepare_report(sms_args()), {"rows": [sms_row(**changes)]})
    assert exc.value.status_code == 502


def test_ad_group_scope_is_validated_against_returned_ids():
    plan = prepare_report(sms_args(ad_group_id="987654321"))
    assert "ad_group.id = 987654321" in plan["query"]
    with pytest.raises(HTTPException) as exc:
        finalize_report(plan, {"rows": [sms_row()]})
    assert exc.value.status_code == 502


@pytest.mark.parametrize("row_date", ["2026-11-15", "2026-11-23", "2026-02-30", None])
def test_daily_result_rejects_wrong_or_missing_dates(row_date):
    plan = prepare_report(sms_args(report="daily"))
    with pytest.raises(HTTPException) as exc:
        finalize_report(plan, {"rows": [sms_row(segments={"date": row_date})]})
    assert exc.value.status_code == 502


def test_daily_results_order_by_date_and_preserve_valid_dates():
    plan = prepare_report(sms_args(report="daily"))
    assert "ORDER BY segments.date ASC, metrics.cost_micros DESC" in plan["query"]
    result = finalize_report(plan, {"rows": [sms_row(segments={"date": "2026-11-16"})]})
    assert result["period"]["mode"] == "inclusive_range"
    assert result["rows"][0]["segments"]["date"] == "2026-11-16"


def test_inconsistent_account_metadata_is_rejected():
    second = deepcopy(sms_row())
    second["customer"]["currencyCode"] = "USD"
    with pytest.raises(HTTPException) as exc:
        finalize_report(prepare_report(sms_args()), {"rows": [sms_row(), second]})
    assert exc.value.status_code == 502


@pytest.mark.parametrize("invalid", ["NaN", "Infinity", "not-a-number", "1.5"])
def test_malformed_micros_cannot_produce_plausible_totals(invalid):
    with pytest.raises(HTTPException) as exc:
        aggregate_metrics([{"metrics": {"costMicros": invalid, "clicks": "4"}}])
    assert exc.value.status_code == 502


def test_original_report_names_remain_available():
    assert set(REPORTS) == {
        "campaigns", "ad_groups", "ads", "keywords", "search_terms", "budgets",
        "daily", "devices", "conversions", "negative_keywords",
    }


@pytest.mark.parametrize("terms", [None, {}, {"searchTerm": ""}, {"searchTerm": 123}])
def test_campaign_configuration_cannot_be_verified_as_actual_search_terms(terms):
    row = sms_row()
    if terms is None:
        row.pop("searchTermView")
    else:
        row["searchTermView"] = terms
    with pytest.raises(HTTPException) as exc:
        finalize_report(prepare_report(sms_args()), {"rows": [row]})
    assert exc.value.status_code == 502
    assert "actual search-term text" in exc.value.detail["message"]


@pytest.mark.parametrize("report,missing_resource", [
    ("ad_groups", "adGroup"), ("keywords", "adGroupCriterion"),
    ("ads", "adGroupAd"), ("devices", "segments"),
])
def test_wrong_report_resource_cannot_produce_verified_performance(report, missing_resource):
    row = sms_row()
    row.pop(missing_resource, None)
    with pytest.raises(HTTPException) as exc:
        finalize_report(prepare_report(sms_args(report=report)), {"rows": [row]})
    assert exc.value.status_code == 502


@pytest.mark.parametrize("report", ["budgets", "conversions"])
def test_configuration_reports_require_their_actual_resource_ids(report):
    plan = prepare_report({"customer_id": "3333735582", "report": report})
    with pytest.raises(HTTPException) as exc:
        finalize_report(plan, {"rows": [sms_row()]})
    assert exc.value.status_code == 502


def test_targeted_keyword_does_not_masquerade_as_negative_keyword():
    plan = prepare_report({"customer_id": "3333735582", "report": "negative_keywords"})
    row = sms_row(adGroupCriterion={"criterionId": "1234", "keyword": {"text": "sms"}, "negative": False})
    with pytest.raises(HTTPException) as exc:
        finalize_report(plan, {"rows": [row]})
    assert exc.value.status_code == 502


def test_selected_zero_metrics_may_be_omitted_without_losing_real_terms():
    result = finalize_report(prepare_report(sms_args()), {"rows": [sms_row(metrics={"impressions": "10"})]})
    assert result["summary"]["clicks"] == 0
    assert result["summary"]["cost"] == "0"
    assert result["rows"][0]["searchTermView"]["searchTerm"] == "رسائل sms للشركات"


@pytest.mark.parametrize("metric", ["clicks", "impressions"])
def test_negative_counts_are_rejected(metric):
    with pytest.raises(HTTPException) as exc:
        aggregate_metrics([{"metrics": {metric: "-1"}}])
    assert exc.value.status_code == 502


def test_fractional_conversion_adjustments_remain_signed():
    result = aggregate_metrics([{"metrics": {"conversions": "-0.5", "conversionsValue": "-12"}}])
    assert result["conversions"] == "-0.5"
    assert result["conversion_value"] == "-12"
