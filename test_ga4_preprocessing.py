from app.analytics.ga4_preprocessing import normalize_ga4_report


def test_normalize_ga4_report():
    payload = {
        "dimensionHeaders": [{"name": "eventName"}],
        "metricHeaders": [{"name": "eventCount"}],
        "rows": [
            {
                "dimensionValues": [{"value": "purchase"}],
                "metricValues": [{"value": "3"}],
            }
        ],
    }
    assert normalize_ga4_report(payload) == [{"eventName": "purchase", "eventCount": 3}]
