import pytest

from app.core.ga4_client import normalize_ga4_filters


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
