"""Expose the existing FastAPI app to Vercel without changing Railway.

The Vercel runtime permits writes under /tmp, not the deployed source tree.
The Vercel environment-variable value itself remains unchanged; only this
process's effective export directory is mapped to a writable location.
"""
import os

if os.environ.get("VERCEL"):
    export_dir = os.environ.get("EXPORT_DIR", "exports")
    if not os.path.isabs(export_dir):
        os.environ["EXPORT_DIR"] = "/tmp/manus-meta/exports"

from app.main import app  # noqa: E402,F401
