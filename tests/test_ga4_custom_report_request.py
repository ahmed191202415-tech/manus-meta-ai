from app.api.ga4 import _custom_report_filters, _custom_report_order_by
from app.schemas.ga4_requests import GA4CustomReportRequest


def test_flat_page_search_and_sort_are_mapped_for_ga4():
    body = GA4CustomReportRequest(
        dimensions=["pagePathPlusQueryString"],
        metrics=["screenPageViews"],
        page_path_contains="verify-otp",
        sort=[{"type": "metric", "name": "screenPageViews", "descending": True}],
    )

    assert _custom_report_filters(body) == {"page_path_contains": "verify-otp"}
    assert _custom_report_order_by(body) == [
        {
            "type": "metric",
            "name": "screenPageViews",
            "descending": True,
            "order_type": "alphanumeric",
        }
    ]


def test_typed_dimension_and_metric_filters_are_mapped_for_ga4():
    body = GA4CustomReportRequest(
        dimensions=["deviceCategory"],
        metrics=["sessions"],
        dimension_filters=[
            {"dimension": "deviceCategory", "operator": "in_list", "values": ["mobile", "desktop"]},
        ],
        metric_filters=[
            {"metric": "sessions", "operator": "between", "from_value": 10, "to_value": 100},
        ],
    )

    filters = _custom_report_filters(body)

    assert filters["dimension_in_list_filters"][0]["values"] == ["mobile", "desktop"]
    assert filters["metric_between_filters"][0]["from"] == 10.0
    assert filters["metric_between_filters"][0]["to"] == 100.0
