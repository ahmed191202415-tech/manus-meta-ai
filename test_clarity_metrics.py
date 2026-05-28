from app.analytics.clarity_metrics import normalize_clarity_export, summarize_clarity_metrics
from app.analytics.clarity_signals import build_clarity_signals
from app.core.clarity_client import _response_payload


class DummyResponse:
    text = ""
    status_code = 400
    reason = "Bad Request"

    def json(self):
        raise ValueError("no json")


def test_clarity_metrics_and_signals_detect_frustration():
    rows = normalize_clarity_export(
        {
            "raw": [
                {
                    "metricName": "Traffic",
                    "information": [
                        {"totalSessionCount": "100", "URL": "/pricing", "scrollDepth": 25, "deadClickCount": 10}
                    ],
                }
            ]
        }
    )
    summary = summarize_clarity_metrics(rows)
    signals = build_clarity_signals(summary, rows)
    assert summary["clarity_sessions"] == 100
    assert any(signal["signal"] == "high_user_frustration" for signal in signals)


def test_clarity_empty_error_body_is_descriptive():
    assert _response_payload(DummyResponse()) == {"raw_text": "", "empty_body": True}
