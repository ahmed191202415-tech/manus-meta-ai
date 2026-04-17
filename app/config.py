from pathlib import Path
import os

META_API_VERSION = os.getenv("META_API_VERSION", "v23.0")
META_GRAPH_BASE = os.getenv("META_GRAPH_BASE", "https://graph.facebook.com")
META_APP_SECRET = os.getenv("META_APP_SECRET", "")
META_APP_ID = os.getenv("META_APP_ID", "")
META_OAUTH_REDIRECT_URI = os.getenv("META_OAUTH_REDIRECT_URI", "")
META_OAUTH_SCOPES = os.getenv(
    "META_OAUTH_SCOPES",
    "ads_management,ads_read,business_management,leads_retrieval,pages_show_list,pages_read_engagement,pages_manage_posts,pages_manage_engagement"
)
SESSION_SECRET = os.getenv("SESSION_SECRET", "change-this-in-production")

HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "90"))
DEFAULT_PAGE_LIMIT = int(os.getenv("DEFAULT_PAGE_LIMIT", "100"))
DEFAULT_MAX_PAGES = int(os.getenv("DEFAULT_MAX_PAGES", "20"))
EXPORT_DIR = Path(os.getenv("EXPORT_DIR", "exports")).expanduser().resolve()
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
ALLOW_ORIGINS = os.getenv("ALLOW_ORIGINS", "*").split(",")
