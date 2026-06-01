from app.analytics import preprocessing


def test_fetch_insights_payload_falls_back_to_lightweight_fields(monkeypatch):
    calls = []

    def get_all_pages(path, token, params=None, max_pages=3):
        calls.append(dict(params or {}))
        if params.get("fields") != preprocessing.LIGHTWEIGHT_INSIGHTS_FIELDS:
            raise RuntimeError("ClientResponseError")
        return {"data": [{"campaign_id": "10", "campaign_name": "Campaign", "spend": "1.00"}]}

    monkeypatch.setattr(preprocessing, "meta_get_all_pages", get_all_pages)

    result = preprocessing.fetch_insights_payload(
        "act_1",
        "token",
        params={"fields": preprocessing.DEFAULT_INSIGHTS_FIELDS, "date_preset": "today"},
    )

    assert result["fallback_used"] is True
    assert result["fallback_mode"] == "lightweight_fields_and_filters"
    assert result["data"][0]["campaign_id"] == "10"
    assert len(calls) == 2


def test_fetch_insights_payload_removes_rejected_filter_and_filters_locally(monkeypatch):
    calls = []

    def get_all_pages(path, token, params=None, max_pages=3):
        calls.append(dict(params or {}))
        if params.get("filtering"):
            raise RuntimeError("ClientResponseError")
        return {
            "data": [
                {"campaign_id": "10", "campaign_name": "Wanted"},
                {"campaign_id": "11", "campaign_name": "Other"},
            ]
        }

    monkeypatch.setattr(preprocessing, "meta_get_all_pages", get_all_pages)

    result = preprocessing.fetch_insights_payload(
        "act_1",
        "token",
        params={
            "fields": preprocessing.LIGHTWEIGHT_INSIGHTS_FIELDS,
            "filtering": [{"field": "campaign.name", "operator": "CONTAIN", "value": "Want"}],
        },
    )

    assert result["fallback_mode"] == "requested_fields_local_filter"
    assert result["local_filter_used"] is True
    assert result["data"] == [{"campaign_id": "10", "campaign_name": "Wanted"}]
    assert len(calls) == 2


def test_fetch_insights_payload_uses_direct_campaign_insights_before_account_request(monkeypatch):
    calls = []

    def get_all_pages(path, token, params=None, max_pages=3):
        calls.append((path, dict(params or {})))
        if path == "act_1/insights":
            raise RuntimeError("ClientResponseError")
        return {"data": [{"campaign_id": "10", "spend": "2.00"}]}

    monkeypatch.setattr(preprocessing, "meta_get_all_pages", get_all_pages)

    result = preprocessing.fetch_insights_payload(
        "act_1",
        "token",
        params={
            "fields": preprocessing.DEFAULT_INSIGHTS_FIELDS,
            "filtering": [{"field": "campaign.id", "operator": "IN", "value": ["10"]}],
        },
    )

    assert result["fallback_mode"] == "direct_object_insights"
    assert result["meta_insights_path"] == "10/insights"
    assert calls == [("10/insights", {"fields": preprocessing.DEFAULT_INSIGHTS_FIELDS})]


def test_fetch_insights_payload_uses_direct_campaign_lightweight_fields_next(monkeypatch):
    calls = []

    def get_all_pages(path, token, params=None, max_pages=3):
        calls.append((path, dict(params or {})))
        if params.get("fields") != preprocessing.LIGHTWEIGHT_INSIGHTS_FIELDS:
            raise RuntimeError("ClientResponseError")
        return {"data": [{"campaign_id": "10", "spend": "2.00"}]}

    monkeypatch.setattr(preprocessing, "meta_get_all_pages", get_all_pages)

    result = preprocessing.fetch_insights_payload(
        "act_1",
        "token",
        params={
            "fields": preprocessing.DEFAULT_INSIGHTS_FIELDS,
            "filtering": [{"field": "campaign.id", "operator": "IN", "value": ["10"]}],
        },
    )

    assert result["fallback_mode"] == "direct_object_lightweight_fields"
    assert result["meta_insights_path"] == "10/insights"
    assert len(calls) == 2
