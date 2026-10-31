"""Vercel smoke tests do not require external Meta/Google credentials."""
import importlib
from pathlib import Path

from fastapi import FastAPI


def test_root_entrypoint_reuses_existing_app(monkeypatch, tmp_path):
    monkeypatch.setenv("VERCEL", "1")
    # Original app.config may already be imported by another test.
    entrypoint = importlib.import_module("index")
    from app.main import app
    assert entrypoint.app is app
    assert isinstance(entrypoint.app, FastAPI)
    paths = entrypoint.app.openapi()["paths"]
    for path in ("/analysis/run", "/meta/query", "/meta/request",
                 "/comment_automations/manage", "/tools/ga4", "/tools/reports"):
        assert path in paths


def test_vercel_output_path_is_temporary_in_fresh_process():
    import os
    import subprocess
    import sys

    env = dict(os.environ, VERCEL="1")
    env.pop("EXPORT_DIR", None)
    script = "import index; from app.config import EXPORT_DIR; print(EXPORT_DIR)"
    result = subprocess.run(
        [sys.executable, "-c", script],
        env=env, text=True, capture_output=True, timeout=45,
        check=True,
    )
    assert result.stdout.strip().endswith("/tmp/manus-meta/exports")
    assert Path(result.stdout.strip()).is_dir()


def test_excel_report_uses_ephemeral_vercel_filesystem():
    """Do not imply persistence: test output only for this request's process."""
    import os
    import pytest
    from fastapi.testclient import TestClient
    if not os.environ.get("VERCEL"):
        pytest.skip("Only asserts Vercel environment export behavior")
    from index import app

    with TestClient(app) as client:
        response = client.post("/reports/save_excel", json={
            "file_name": "vercel-smoke.xlsx",
            "title": "Vercel smoke",
            "sheets": [{"name": "Results", "headers": ["Campaign", "Spend"],
                         "rows": [["Test", 10]]}],
        })
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["success"] is True
        assert payload["file_path"].startswith("/tmp/manus-meta/exports/")
        assert Path(payload["file_path"]).is_file()
