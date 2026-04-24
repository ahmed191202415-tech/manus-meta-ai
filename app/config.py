from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()

META_API_VERSION = os.getenv("META_API_VERSION", "v23.0")
META_GRAPH_BASE = os.getenv("META_GRAPH_BASE", "https://graph.facebook.com")
META_APP_SECRET = os.getenv("META_APP_SECRET", "")
META_APP_ID = os.getenv("META_APP_ID", "")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
META_OAUTH_REDIRECT_URI = os.getenv(
    "META_OAUTH_REDIRECT_URI",
    f"{PUBLIC_BASE_URL}/auth/meta/callback" if PUBLIC_BASE_URL else "",
)
META_OAUTH_SCOPES = os.getenv(
    "META_OAUTH_SCOPES",
    "ads_management,ads_read,business_management,leads_retrieval,pages_show_list,pages_read_engagement,pages_manage_posts,pages_manage_engagement"
)
SESSION_SECRET = os.getenv("SESSION_SECRET", "change-this-in-production")
PORTAL_PATH = os.getenv("PORTAL_PATH", "/portal")
PORTAL_INVITE_SALT = os.getenv("PORTAL_INVITE_SALT", "portal-invite")
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "").strip().lower()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")

HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "90"))
DEFAULT_PAGE_LIMIT = int(os.getenv("DEFAULT_PAGE_LIMIT", "100"))
DEFAULT_MAX_PAGES = int(os.getenv("DEFAULT_MAX_PAGES", "20"))
META_RETRY_MAX_ATTEMPTS = int(os.getenv("META_RETRY_MAX_ATTEMPTS", "4"))
META_RETRY_BASE_DELAY_SECONDS = float(os.getenv("META_RETRY_BASE_DELAY_SECONDS", "2.0"))
EXPORT_DIR = Path(os.getenv("EXPORT_DIR", "exports")).expanduser().resolve()
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
ALLOW_ORIGINS = os.getenv("ALLOW_ORIGINS", "*").split(",")
