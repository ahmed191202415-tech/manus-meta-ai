"""Google Ads report intent should never silently inspect a named campaign."""
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from app.core import google_ads_gateway as ads


def parse(text):
    return ads.parse_google_ads_request(SimpleNamespace(
        request=text, meta_account_id=None, campaign_name=None))


@pytest.mark.parametrize("request_text", [
    "google_ads نتائج النهارده 2026-11-22 لحملة Sales-Search-1 customer_id 3333735582",
    "Google Ads performance report Sales-Search-1 account 3333735582 on 2026-11-22",
    "google_ads report=campaigns customer_id 3333735582 Sales-Search-1 2026-11-22",
    "google_ads report=daily customer_id 3333735582 Sales-Search-1 date=2026-11-22",
])
def test_explicit_dated_campaign_performance_not_inspection(request_text):
    cmd = parse(request_text)
    assert cmd["action"] == "report"
    assert cmd["customer_id"] == "3333735582"
    assert cmd["date"] == "2026-11-22"


def test_gaql_not_interpreted_as_inspect_campaign():
    text = ("google_ads customer_id 3333735582 GoogleAdsService.SearchStream "
            "SELECT campaign.id, campaign.name, metrics.cost_micros "
            "FROM campaign WHERE segments.date = '2026-11-22'")
    cmd = parse(text)
    assert cmd["action"] == "query"
    assert cmd["customer_id"] == "3333735582"
    assert cmd["search_stream"] is True
    assert cmd["query"].startswith("SELECT campaign.id")


def test_specific_date_builds_exact_gaql_and_uses_search_stream(monkeypatch):
    calls = []
    def fake_stream(query, tenant, customer_id, manager_id=None, limit=100):
        calls.append((query, tenant, customer_id))
        return {"rows": [{
            "campaign": {"id": "24412747386", "name": "Sales-Search-1"},
            "metrics": {"costMicros": "2400000", "clicks": "4", "impressions": "30", "conversions": "1", "conversionsValue": "12"},
        }], "count": 1, "truncated": False, "query_method": "GoogleAdsService.SearchStream"}
    monkeypatch.setattr(ads, "_read_stream", fake_stream)
    result = ads._report("tenant", {"customer_id": "3333735582", "report": "campaigns", "date": "2026-11-22"})
    assert result["date_range"] == "2026-11-22"
    assert result["query_method"] == "GoogleAdsService.SearchStream"
    assert "WHERE segments.date = '2026-11-22'" in calls[0][0]
    assert result["summary"]["clicks"] == 4
    assert result["summary"]["cost"] == "2.4"


def test_stream_batches_are_combined(monkeypatch):
    monkeypatch.setattr(ads, "_api", lambda *a, **kw: [
        {"results": [{"campaign": {"id": "1"}}]},
        {"results": [{"campaign": {"id": "2"}}]}
    ])
    result = ads._read_stream("SELECT campaign.id FROM campaign", "tenant", "3333735582")
    assert result["count"] == 2
    assert result["query_method"] == "GoogleAdsService.SearchStream"


@pytest.mark.parametrize("bad_date", ["2026-13-22", "2026-11-22' OR 1=1", "2026-02-30"])
def test_invalid_dates_rejected_before_query(monkeypatch, bad_date):
    monkeypatch.setattr(ads, "_read_stream", lambda *args, **kw: pytest.fail("Unsafe date must not be queried"))
    with pytest.raises(HTTPException) as exc:
        ads._report("tenant", {"customer_id": "3333735582", "date": bad_date})
    assert exc.value.status_code == 422


def test_inspection_remains_explicit():
    assert parse("google_ads افحص Sales-Search-1 customer_id 3333735582")["action"] == "inspect_campaign"
