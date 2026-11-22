"""Prevent concurrent OAuth or Ads-approval redeems from succeeding twice."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier, Lock

import pytest
import requests

from app.core import oauth_store as store


def test_concurrent_consumers_use_one_conditional_write(monkeypatch):
    now = datetime(2026, 11, 22, 18, tzinfo=timezone.utc)
    row = {"code": "code_test", "tenant_id": "tenant-a", "meta_user_id": "google_ads_mutation_approval", "used": False, "expires_at": (now + timedelta(minutes=10)).isoformat()}
    barrier, lock = Barrier(2), Lock()
    calls = []
    monkeypatch.setattr(store, "_now_utc", lambda: now)
    monkeypatch.setattr(store, "_get_single", lambda *a, **k: pytest.fail("A read before claim is not atomic"))
    def conditional_patch(table, params, payload, prefer):
        assert table == "oauth_codes"
        assert params == {"code": "eq.code_test", "used": "eq.false", "expires_at": "gt." + now.isoformat()}
        assert payload == {"used": True} and prefer == "return=representation"
        calls.append(params)
        barrier.wait(timeout=5)
        with lock:
            if row["used"]:
                return []
            row["used"] = True
            return [dict(row)]
    monkeypatch.setattr(store, "_patch", conditional_patch)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(store.consume_auth_code, ["code_test", "code_test"]))
    assert len(calls) == 2
    assert sum(result is not None for result in results) == 1
    winner = next(result for result in results if result)
    assert winner["tenant_id"] == "tenant-a"
    assert winner["used"] is True


@pytest.mark.parametrize("response", [[], None, {}, [{"code": "code_test", "used": False}], [{"code": "different", "used": True}]])
def test_no_updated_matching_row_never_authorizes_mutation(monkeypatch, response):
    monkeypatch.setattr(store, "_patch", lambda *a, **k: response)
    assert store.consume_auth_code("code_test") is None


def test_empty_code_does_not_touch_storage(monkeypatch):
    monkeypatch.setattr(store, "_patch", lambda *a, **k: pytest.fail("No storage access expected"))
    assert store.consume_auth_code(" ") is None


def test_claim_transport_failure_does_not_retry_or_fall_back(monkeypatch):
    calls = []
    def failed(*args, **kwargs):
        calls.append(1)
        raise requests.Timeout()
    monkeypatch.setattr(store, "_patch", failed)
    monkeypatch.setattr(store, "_get_single", lambda *a, **k: pytest.fail("No non-atomic fallback allowed"))
    with pytest.raises(requests.Timeout):
        store.consume_auth_code("code_test")
    assert calls == [1]
