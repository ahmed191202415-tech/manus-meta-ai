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
