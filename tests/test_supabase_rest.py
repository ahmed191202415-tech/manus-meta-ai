import pytest

from app.core.supabase_rest import SupabaseRestClient


class FakeResponse:
    def __init__(self, payload=None, text="payload"):
        self.payload = payload
        self.text = text
        self.raised = False

    def raise_for_status(self):
        self.raised = True

    def json(self):
        return self.payload


class FakeTransport:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def __getattr__(self, method):
        def call(url, **kwargs):
            self.calls.append((method, url, kwargs))
            return self.response

        return call


def test_get_many_uses_one_consistent_authenticated_transport_boundary():
    response = FakeResponse([{"id": "row_1"}])
    transport = FakeTransport(response)
    client = SupabaseRestClient("https://example.supabase.co/", "secret", transport)

    assert client.get_many("connections", {"limit": 1}) == [{"id": "row_1"}]
    method, url, kwargs = transport.calls[0]
    assert method == "get"
    assert url == "https://example.supabase.co/rest/v1/connections"
    assert kwargs["headers"]["Authorization"] == "Bearer secret"
    assert kwargs["timeout"] == 30
    assert response.raised is True


def test_empty_mutation_response_is_handled_without_json_decode_error():
    response = FakeResponse(text="")
    transport = FakeTransport(response)
    client = SupabaseRestClient("https://example.supabase.co", "secret", transport)

    assert client.patch("connections", {"id": "eq.1"}, {"active": False}) is None
    assert response.raised is True


def test_client_rejects_unconfigured_access_before_network_call():
    transport = FakeTransport(FakeResponse([]))
    client = SupabaseRestClient("", "", transport)

    with pytest.raises(RuntimeError, match="SUPABASE_URL"):
        client.get_many("connections")
    assert transport.calls == []


def test_client_rejects_table_path_injection():
    transport = FakeTransport(FakeResponse([]))
    client = SupabaseRestClient("https://example.supabase.co", "secret", transport)

    with pytest.raises(ValueError, match="table name"):
        client.get_many("connections?select=*")

