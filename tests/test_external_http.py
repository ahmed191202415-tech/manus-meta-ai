import pytest
from fastapi import HTTPException

from app.core.external_http import require_object, response_json
from app.core.ga4_requests import build_funnel_request, build_report_request


class InvalidJsonResponse:
    status_code = 502
    text = "<html>upstream failure</html>"

    def json(self):
        raise ValueError("not json")


def test_invalid_upstream_json_becomes_safe_gateway_error():
    with pytest.raises(HTTPException) as error:
        response_json(InvalidJsonResponse(), "GA4")

    assert error.value.status_code == 502
    assert "invalid response" in error.value.detail["message"]
    assert "upstream failure" in error.value.detail["response_preview"]


def test_non_object_upstream_payload_is_rejected():
    with pytest.raises(HTTPException, match="unexpected response shape"):
        require_object([], "GA4")


def test_ga4_report_requires_metrics_before_network_request():
    with pytest.raises(HTTPException, match="metric"):
        build_report_request([], [], "7daysAgo", "today", 100, 0, None, None, None)


def test_ga4_funnel_validates_every_step():
    with pytest.raises(HTTPException, match="step 1"):
        build_funnel_request([{"name": "Lead"}], "7daysAgo", "today")

