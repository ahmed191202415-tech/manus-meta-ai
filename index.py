"""Vercel FastAPI entrypoint for the existing Railway application.

This file does not replace or duplicate the API.  It only ensures that
temporary report output uses the writable filesystem on Vercel before the
existing application imports its configuration.
"""
import os

if os.environ.get("VERCEL"):
    # Vercel has a read-only app filesystem. Keep the configured EXPORT_DIR\n    # unchanged in Vercel settings while mapping relative paths to /tmp.\n    if not os.path.isabs(os.environ.get("EXPORT_DIR", "exports")):\n        os.environ["EXPORT_DIR"] = "/tmp/manus-meta/exports"

from app.main import app  # noqa: E402,F401
