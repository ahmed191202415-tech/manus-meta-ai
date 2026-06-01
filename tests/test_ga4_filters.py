import pytest

from app.core.ga4_client import normalize_ga4_filters, normalize_ga4_order_bys


def test_page_path_contains_builds_simple_ga4_dimension_filter():
    result = normalize_ga4_filters({"page_path_contains": "verify-otp"})

    assert result == {
        "dimensionFilter": {
            "filter": {
                "fieldName": "pagePathPlusQueryString",
                "stringFilter": {
                    "matchType": "CONTAINS",
                    "value": "verify-otp",
                    "caseSensitive": False,
                },
            }
        }
    }


def test_dimension_string_filters_are_combined_with_and_group():
    result = normalize_ga4_filters(
        {
            "page_path_contains": "verify-otp",
            "dimension_string_filters": [
                {
                    "dimension": "deviceCategory",
                    "operator": "exact",
                    "value": "mobile",
                }
            ],
        }
    )

    assert len(result["dimensionFilter"]["andGroup"]["expressions"]) == 2


def test_dimension_string_filter_rejects_invalid_dimension():
    with pytest.raises(Exception):
        normalize_ga4_filters(
            {
                "dimension_string_filters": [
                    {"dimension": "pagePath;drop", "value": "verify-otp"},
                ]
            }
        )


def test_custom_filters_support_in_list_empty_numeric_and_between():
    result = normalize_ga4_filters(
        {
            "dimension_in_list_filters": [
                {"dimension": "deviceCategory", "values": ["mobile", "desktop"]},
            ],
            "dimension_empty_filters": [
                {"dimension": "sessionCampaignName", "exclude": True},
            ],
            "metric_numeric_filters": [
                {"metric": "sessions", "operator": "greater_than", "value": 10},
            ],
            "metric_between_filters": [
                {"metric": "engagementRate", "from": 0.2, "to": 0.8},
            ],
        }
    )

    assert len(result["dimensionFilter"]["andGroup"]["expressions"]) == 2
    assert len(result["metricFilter"]["andGroup"]["expressions"]) == 2
    assert result["metricFilter"]["andGroup"]["expressions"][0]["filter"]["numericFilter"]["operation"] == "GREATER_THAN"


def test_order_by_supports_simple_metric_and_dimension_forms():
    result = normalize_ga4_order_bys(
        [
            {"type": "metric", "name": "sessions", "descending": True},
            {"type": "dimension", "name": "date", "order_type": "numeric"},
        ]
    )

    assert result == [
        {"desc": True, "metric": {"metricName": "sessions"}},
        {"desc": False, "dimension": {"dimensionName": "date", "orderType": "NUMERIC"}},
    ]
