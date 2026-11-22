"""User-visible Google Ads scopes must survive Actions intent parsing."""
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.google_ads_intent import detect_google_ads_request, parse_google_ads_request


def parse(message, **fields):
    return parse_google_ads_request(SimpleNamespace(request=message, **fields))


@pytest.mark.parametrize("message", [
    'google_ads Search Terms الفعلية لحملة «sms حملة» Campaign ID 24445941074 customer_id 3333735582 من 16–22 نوفمبر 2026',
    'Google Ads search_term_view campaign_id=24445941074 customer_id=3333735582 2026-11-16 to 2026-11-22',
    'Google Ads search terms campaign_id 24445941074 account 3333735582 16-22 November 2026',
])
def test_search_terms_preserve_requested_resource_campaign_and_full_interval(message):
    command = parse(message)
    assert command["action"] == "report"
    assert command["report"] == "search_terms"
    assert command["customer_id"] == "3333735582"
    assert command["campaign_id"] == "24445941074"
    assert command["start_date"] == "2026-11-16"
    assert command["end_date"] == "2026-11-22"
    assert "date" not in command
    assert "date_range" not in command


def test_arabic_campaign_name_and_digits_are_preserved():
    command = parse('google_ads تقرير Search Terms لحملة «sms حملة» customer_id ٣٣٣٣٧٣٥٥٨٢ الفترة ١٦–٢٢ نوفمبر ٢٠٢٦')
    assert command["campaign_name"] == "sms حملة"
    assert command["customer_id"] == "3333735582"
    assert command["start_date"] == "2026-11-16"


@pytest.mark.parametrize("query", [
    'SELECT campaign.id FROM campaign WHERE campaign.name = "sms حملة"',
    'SELECT campaign.id FROM campaign WHERE campaign.name = "حملة ١"',
    "SELECT campaign.id FROM campaign WHERE campaign.name = 'owner\\'s campaign'",
    "SELECT campaign.id FROM campaign WHERE segments.date BETWEEN '2026-11-16' AND '2026-11-22'",
])
def test_unfenced_gaql_is_not_changed(query):
    message = "GoogleAdsService.SearchStream customer_id 3333735582 " + query
    assert detect_google_ads_request(message)
    command = parse(message)
    assert command["action"] == "query"
    assert command["query"] == query


def test_fenced_gaql_has_exact_boundaries_even_with_following_prose():
    query = 'SELECT search_term_view.search_term FROM search_term_view WHERE campaign.name = "sms حملة"'
    command = parse('google_ads account 3333735582\n```gaql\n' + query + '\n```\nExplain the result.')
    assert command["query"] == query


def test_structured_and_natural_campaign_names_are_never_digit_normalized():
    command = parse('google_ads {"action":"report","customer_id":"3333735582","campaign_name":"حملة ١"}')
    assert command["campaign_name"] == "حملة ١"
    command = parse('google_ads تقرير لحملة «حملة ١» customer_id ٣٣٣٣٧٣٥٥٨٢ ٢٠٢٦-١١-٢٢')
    assert command["campaign_name"] == "حملة ١"
    assert command["date"] == "2026-11-22"


def test_dates_in_campaign_names_are_not_reporting_dates():
    command = parse('google_ads performance campaign "Launch 2026-11-16" account 3333735582 today')
    assert command["date_range"] == "TODAY"
    assert "date" not in command
    command = parse('google_ads performance Launch-2026-11-16 account 3333735582 yesterday')
    assert command["date_range"] == "YESTERDAY"


@pytest.mark.parametrize("suffix", [
    "\nand explain the result",
    " and report the findings.",
    "\nواشرح النتيجة",
    "\n```",
])
def test_ambiguous_unfenced_gaql_never_reaches_provider(suffix):
    with pytest.raises(HTTPException) as exc:
        parse("google_ads customer_id 3333735582 SELECT campaign.id FROM campaign" + suffix)
    assert exc.value.status_code == 422


@pytest.mark.parametrize("message", [
    '{"provider":"google_ads","action":"report","customer_id":"3333735582","report":"search_terms"}',
    '```json\n{"action":"report","customer_id":"3333735582","report":"search_terms"}\n```',
    'google_ads {"action":"report","customer_id":"3333735582","report":"search_terms"}',
])
def test_structured_google_ads_commands_retain_read_scope_defaults(message):
    assert detect_google_ads_request(message)
    command = parse(message, campaign_id="24445941074", start_date="2026-11-16", end_date="2026-11-22", limit=250)
    assert command["report"] == "search_terms"
    assert command["campaign_id"] == "24445941074"
    assert command["start_date"] == "2026-11-16"
    assert command["end_date"] == "2026-11-22"
    assert command["limit"] == 250


def test_json_scope_is_authoritative_over_body_defaults():
    command = parse('google_ads {"action":"report","customer_id":"3333735582","report":"campaigns",'
                    '"campaign_id":"24445941074","date":"2026-11-22","limit":10}',
                    campaign_id="999", start_date="2000-01-01", end_date="2000-01-02", limit=250)
    assert command["campaign_id"] == "24445941074"
    assert command["date"] == "2026-11-22"
    assert "start_date" not in command
    assert command["limit"] == 10


@pytest.mark.parametrize("scope", [
    {"campaign_id": "24445941074"}, {"campaign_name": "sms حملة"},
    {"start_date": "2026-11-16", "end_date": "2026-11-22"}, {"date_preset": "today"},
])
def test_raw_query_never_silently_ignores_top_level_read_filters(scope):
    query = 'SELECT campaign.id FROM campaign'
    for message in (
        'google_ads ' + json.dumps({"action": "query", "customer_id": "3333735582", "query": query}),
        'google_ads customer_id 3333735582 ' + query,
    ):
        with pytest.raises(HTTPException) as exc:
            parse(message, **scope)
        assert exc.value.status_code == 422
        assert "GAQL" in exc.value.detail


def test_raw_query_never_silently_ignores_natural_campaign_scope():
    with pytest.raises(HTTPException):
        parse('google_ads customer_id 3333735582 campaign_id 24445941074 SELECT campaign.id FROM campaign')


def test_raw_query_never_silently_ignores_dates_outside_the_statement():
    with pytest.raises(HTTPException):
        parse('google_ads customer_id 3333735582 date=2026-11-22 SELECT campaign.id FROM campaign')


def test_resource_alias_is_accepted_in_natural_report_command():
    from app.core.google_ads_reporting import prepare_report
    command = parse('google_ads report=search_term_view customer_id 3333735582 campaign_id 24445941074 2026-11-16 to 2026-11-22')
    assert prepare_report(command)["report"] == "search_terms"


@pytest.mark.parametrize("message", [
    '[{"provider":"google_ads","action":"report","customer_id":"3333735582"}]',
    '{"provider":"google_ads","action":"report","customer_id":"3333735582"} extra text',
    'google_ads {"action":"report","report":"search_terms",}',
    'google_ads {"action":"query","query":}',
])
def test_unknown_wrappers_and_malformed_reports_fail_closed(message):
    with pytest.raises(HTTPException) as exc:
        parse(message)
    assert exc.value.status_code == 422


def test_other_provider_json_is_not_hijacked():
    assert not detect_google_ads_request('{"provider":"meta","action":"report","customer_id":"3333735582"}')
    assert not detect_google_ads_request("اعمل تحليل ميتا")


def test_customer_id_is_not_guessed_from_campaign_or_manager():
    command = parse("google_ads search terms campaign_id 1234567890 manager_id 9876543210 2026-11-22")
    assert command["action"] == "list_accounts"
    with pytest.raises(HTTPException):
        parse("google_ads SELECT campaign.id FROM campaign WHERE campaign.id = 1234567890")


def test_manager_id_does_not_replace_actual_customer():
    command = parse("google_ads search terms manager_id 9876543210 customer_id 3333735582 campaign_id 24445941074")
    assert command["customer_id"] == "3333735582"
    assert command["manager_id"] == "9876543210"


def test_space_separated_login_customer_id_is_never_target_customer():
    command = parse("google_ads search terms login customer id 9876543210 campaign_id 24445941074")
    assert command["action"] == "list_accounts"
    command = parse("google_ads search terms login customer id 9876543210 customer id 3333735582 campaign_id 24445941074")
    assert command["customer_id"] == "3333735582"
    assert command["manager_id"] == "9876543210"


@pytest.mark.parametrize("period", [
    "2026-11-22 to 2026-11-16", "2026-02-30", "16-22 November",
    "start_date=2026-11-16", "last 17 days", "last week", "today and yesterday",
    "2026-11-16 2026-11-20 2026-11-22",
])
def test_ambiguous_or_invalid_periods_are_not_replaced_by_a_default(period):
    with pytest.raises(HTTPException) as exc:
        parse("google_ads report=search_terms customer_id 3333735582 " + period)
    assert exc.value.status_code == 422


@pytest.mark.parametrize("period,expected", [
    ("yesterday", "YESTERDAY"), ("last 14 days", "LAST_14_DAYS"),
    ("الشهر الماضي", "LAST_MONTH"), ("TODAY", "TODAY"),
])
def test_supported_relative_dates_are_preserved(period, expected):
    assert parse("google_ads daily account 3333735582 " + period)["date_range"] == expected


def test_campaign_request_missing_identity_is_not_broadened_to_account():
    with pytest.raises(HTTPException):
        parse("google ads search terms for campaign customer_id 3333735582")


def test_keyword_inventory_and_search_terms_remain_distinct():
    inventory = parse("google ads keywords campaign_id=24445941074 ad_group_id=201563783253 customer_id=3333735582 Sales-Search-crm")
    assert inventory == {"action": "keyword_inventory", "customer_id": "3333735582", "campaign_id": "24445941074", "ad_group_id": "201563783253"}
    performance = parse("google ads keyword performance campaign_id=24445941074 customer_id=3333735582 2026-11-22")
    assert performance["action"] == "report"
    assert performance["report"] == "keywords"
    negatives = parse("google ads negative keywords customer_id=3333735582")
    assert negatives["report"] == "negative_keywords"


@pytest.mark.parametrize("report", ["budgets", "conversions", "negative_keywords"])
def test_configuration_reports_do_not_acquire_an_implicit_performance_period(report):
    from app.core.google_ads_reporting import prepare_report
    for message in (
        'google_ads ' + json.dumps({"action": "report", "report": report, "customer_id": "3333735582"}),
        'google_ads report=' + report + ' customer_id 3333735582',
    ):
        command = parse(message)
        assert not any(key in command for key in ("date", "start_date", "end_date", "date_range"))
        plan = prepare_report(command)
        assert plan["report"] == report


def test_configuration_report_retains_explicit_date_to_fail_instead_of_ignoring_it():
    from app.core.google_ads_reporting import prepare_report
    command = parse('google_ads report=budgets customer_id 3333735582 2026-11-22')
    assert command["date"] == "2026-11-22"
    with pytest.raises(HTTPException):
        prepare_report(command)


def test_mutations_do_not_inherit_read_defaults():
    command = {"action": "prepare_mutation", "customer_id": "3333735582", "operations": []}
    parsed = parse("google_ads " + json.dumps(command), campaign_id="24445941074", start_date="2026-11-16", end_date="2026-11-22", limit=250)
    assert parsed == command


@pytest.mark.parametrize("message", [
    'google_ads {"action":"commit_mutation","approval_token":"redacted"} and execute',
    'Please execute google_ads {"action":"prepare_mutation","operations":[]}',
    'google_ads {"action":"prepare_mutation","operations": [}',
    'google_ads {"action":"commit_mutation","approval_token":}',
    'google_ads delete campaign 24445941074 customer_id 3333735582',
])
def test_writes_are_never_inferred_or_repaired(message):
    with pytest.raises(HTTPException) as exc:
        parse(message)
    assert exc.value.status_code == 422
