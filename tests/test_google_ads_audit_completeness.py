"""Truthful diagnostics and completeness on read-only discovery/migration."""
import pytest
from fastapi import HTTPException

from app.core import google_ads_discovery as discovery
from app.core import google_ads_gateway as gateway
from app.core import google_ads_migration_audit as audit


def test_discovery_preserves_safe_request_diagnostics():
    result = discovery._safe_google_ads_error(HTTPException(400, {
        "origin": "google_ads_api", "api_status": "INVALID_ARGUMENT",
        "google_ads_error_code": "UNRECOGNIZED_FIELD",
        "google_ads_error_category": "query", "google_ads_error_field": "query",
        "google_request_id": "6UazGT5sZwCweO5k14CoRw",
    }))
    assert result["google_request_id"] == "6UazGT5sZwCweO5k14CoRw"
    assert result["google_ads_error_category"] == "query"
    assert result["google_ads_error_field"] == "query"


def test_all_failed_campaign_reads_are_not_marked_verified(monkeypatch):
    def failed(*args, **kwargs):
        raise HTTPException(400, {"origin": "google_ads_api", "google_ads_error_code": "UNRECOGNIZED_FIELD"})
    monkeypatch.setattr(gateway, "_read", failed)
    result = discovery.inspect_campaign_live("tenant-a", "sms حملة", customer_id="3333735582", date_range="TODAY")
    assert result["verified_by_google_api"] is False
    assert result["campaign_data_verified"] is False
    assert result["google_api_called"] is True
    assert result["date_range"] == "TODAY"
    assert result["read_complete"] is False


def test_campaign_configuration_reports_metrics_period_and_group_limit(monkeypatch):
    def read(query, *args, **kwargs):
        if "FROM campaign" in query:
            return {"rows": [{"campaign": {"id": "24445941074", "name": "sms حملة"}}]}
        assert "LAST_7_DAYS" in query and "LIMIT 101" in query
        assert kwargs["limit"] == 101
        return {"rows": [{"adGroup": {"id": str(i)}} for i in range(101)]}
    monkeypatch.setattr(gateway, "_read", read)
    result = discovery.inspect_campaign_live("tenant-a", "sms حملة", customer_id="3333735582")
    campaign = result["campaigns"][0]
    assert campaign["metrics_date_range"] == "LAST_7_DAYS"
    assert campaign["ad_groups_verified"] is True
    assert campaign["ad_groups_truncated"] is True
    assert len(campaign["ad_groups"]) == 100
    assert result["read_complete"] is False


@pytest.mark.parametrize("keyword_count, complete", [(200, True), (201, False)])
def test_audit_fetches_extra_row_to_prove_completeness(monkeypatch, keyword_count, complete):
    def read(query, *args, **kwargs):
        if "FROM campaign WHERE" in query:
            return {"rows": [{"campaign": {"id": "44"}}]}
        if "FROM ad_group WHERE" in query:
            return {"rows": [{"campaign": {"id": "44"}, "adGroup": {"id": "55"}}]}
        if "FROM ad_group_criterion" in query and "type = 'KEYWORD'" in query:
            assert "LIMIT 201" in query and kwargs["limit"] == 201
            return {"rows": [{"adGroupCriterion": {"criterionId": str(i)}} for i in range(keyword_count)], "truncated": False}
        return {"rows": [], "truncated": False}
    monkeypatch.setattr(gateway, "_read", read)
    result = audit.audit_crm_migration("tenant-a", "3333735582", "44", "55")
    assert result["audit_complete"] is complete
    assert result["sections"]["keywords"]["count"] == 200
    assert result["sections"]["keywords"]["truncated"] is not complete
    assert result["safe_to_clone_automatically"] is False


@pytest.mark.parametrize("dates, clause, mode, expected_range", [
    ({"date": "2026-11-22"}, "segments.date = '2026-11-22'", "date", "2026-11-22"),
    ({"start_date": "2026-11-16", "end_date": "2026-11-22"}, "segments.date BETWEEN '2026-11-16' AND '2026-11-22'", "inclusive_range", "2026-11-16..2026-11-22"),
])
def test_inspection_preserves_exact_dates_and_campaign_id(monkeypatch, dates, clause, mode, expected_range):
    calls = []
    def read(query, *args, **kwargs):
        calls.append(query)
        if "FROM campaign" in query:
            assert "campaign.name = 'sms حملة'" in query
            assert "campaign.id = 24445941074" in query
            return {"rows": [{"customer": {"currencyCode": "EGP", "timeZone": "Africa/Cairo"}, "campaign": {"id": "24445941074", "name": "sms حملة"}}]}
        assert clause in query and "LAST_7_DAYS" not in query
        return {"rows": [{"adGroup": {"id": "55"}, "metrics": {"costMicros": "1000000"}}]}
    monkeypatch.setattr(gateway, "_read", read)
    result = discovery.inspect_campaign_live("tenant-a", "sms حملة", customer_id="3333735582", campaign_id="24445941074", **dates)
    assert len(calls) == 2
    assert result["date_range"] == expected_range
    assert result["period"]["mode"] == mode
    assert result["campaign_id"] == "24445941074"
    campaign = result["campaigns"][0]
    assert campaign["metrics_date_range"] == expected_range
    assert campaign["metrics_period"] == result["period"]
    assert campaign["currency"] == "EGP"
    assert campaign["time_zone"] == "Africa/Cairo"


def test_inspection_accepts_campaign_id_without_guessing_a_name(monkeypatch):
    def read(query, *args, **kwargs):
        if "FROM campaign" in query:
            assert "WHERE campaign.id = 24445941074" in query
            return {"rows": [{"campaign": {"id": "24445941074", "name": "sms حملة"}}]}
        return {"rows": []}
    monkeypatch.setattr(gateway, "_read", read)
    result = discovery.inspect_campaign_live("tenant-a", customer_id="3333735582", campaign_id="24445941074")
    assert result["campaign_name"] is None
    assert result["campaigns"][0]["campaign_name"] == "sms حملة"


@pytest.mark.parametrize("dates", [
    {"date_range": "ALL_TIME"}, {"date": "2026-02-30"}, {"start_date": "2026-11-16"},
    {"date": "2026-11-22", "start_date": "2026-11-16", "end_date": "2026-11-22"},
    {"start_date": "2026-11-22", "end_date": "2026-11-16"},
])
def test_invalid_inspection_period_fails_before_any_api_read(monkeypatch, dates):
    monkeypatch.setattr(gateway, "_read", lambda *a, **k: pytest.fail("No API read expected"))
    monkeypatch.setattr(discovery, "list_accounts_live", lambda *a, **k: pytest.fail("No account lookup expected"))
    with pytest.raises(HTTPException) as caught:
        discovery.inspect_campaign_live("tenant-a", "sms حملة", **dates)
    assert caught.value.status_code == 422


def test_wrong_campaign_id_is_never_returned_from_inspection(monkeypatch):
    monkeypatch.setattr(gateway, "_read", lambda *a, **k: {"rows": [{"campaign": {"id": "999", "name": "sms حملة"}}]})
    with pytest.raises(HTTPException) as caught:
        discovery.inspect_campaign_live("tenant-a", "sms حملة", customer_id="3333735582", campaign_id="24445941074")
    assert caught.value.status_code == 502
