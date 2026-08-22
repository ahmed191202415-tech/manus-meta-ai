import pytest
from fastapi import HTTPException
from requests import ConnectionError

from app.core import http_client, meta_client


class FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self.payload = payload
        self.text = ""

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def request(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_http_adapter_never_automatically_retries_post():
    session = http_client.create_retry_session()

    assert "POST" not in session.adapters["https://"].max_retries.allowed_methods
    assert "GET" in session.adapters["https://"].max_retries.allowed_methods


def test_meta_post_is_not_retried_after_transient_response(monkeypatch):
    session = FakeSession([FakeResponse(500, {"error": {"message": "temporary", "is_transient": True}})])
    monkeypatch.setattr(meta_client, "SESSION", session)

    with pytest.raises(HTTPException):
        meta_client.meta_call("POST", "comment_1/comments", "token", data={"message": "Thanks"})

    assert len(session.calls) == 1


def test_meta_post_is_not_retried_after_network_error(monkeypatch):
    session = FakeSession([ConnectionError("connection lost")])
    monkeypatch.setattr(meta_client, "SESSION", session)

    with pytest.raises(HTTPException) as error:
        meta_client.meta_call("POST", "comment_1/comments", "token", data={"message": "Thanks"})

    assert error.value.status_code == 502
    assert len(session.calls) == 1


def test_meta_get_retries_transient_response(monkeypatch):
    session = FakeSession([
        FakeResponse(500, {"error": {"message": "temporary", "is_transient": True}}),
        FakeResponse(200, {"data": [{"id": "1"}]}),
    ])
    monkeypatch.setattr(meta_client, "SESSION", session)
    monkeypatch.setattr(meta_client.time, "sleep", lambda seconds: None)

    assert meta_client.meta_call("GET", "me/adaccounts", "token")["data"][0]["id"] == "1"
    assert len(session.calls) == 2

