from pathlib import Path
import os

META_API_VERSION = os.getenv("META_API_VERSION", "v23.0")
META_GRAPH_BASE = os.getenv("META_GRAPH_BASE", "https://graph.facebook.com")
META_APP_SECRET = os.getenv("META_APP_SECRET", "")
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "90"))
DEFAULT_PAGE_LIMIT = int(os.getenv("DEFAULT_PAGE_LIMIT", "100"))
DEFAULT_MAX_PAGES = int(os.getenv("DEFAULT_MAX_PAGES", "20"))
EXPORT_DIR = Path(os.getenv("EXPORT_DIR", "exports")).expanduser().resolve()
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
ALLOW_ORIGINS = os.getenv("ALLOW_ORIGINS", "*").split(",")