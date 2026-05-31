from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()

ENVIRONMENT = os.getenv("ENVIRONMENT", os.getenv("APP_ENV", "development")).lower()
IS_PRODUCTION = ENVIRONMENT in {"prod", "production"}


def _env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


META_API_VERSION = os.getenv("META_API_VERSION", "v23.0")
META_GRAPH_BASE = os.getenv("META_GRAPH_BASE", "https://graph.facebook.com")
META_APP_SECRET = os.getenv("META_APP_SECRET", "")
META_APP_ID = os.getenv("META_APP_ID", "")
META_TEST_ACCESS_TOKEN = os.getenv("META_TEST_ACCESS_TOKEN", "").strip()
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
META_OAUTH_REDIRECT_URI = os.getenv(
    "META_OAUTH_REDIRECT_URI",
    f"{PUBLIC_BASE_URL}/auth/meta/callback" if PUBLIC_BASE_URL else "",
)
META_OAUTH_SCOPES = os.getenv(
    "META_OAUTH_SCOPES",
    "ads_management,ads_read,business_management,leads_retrieval,pages_show_list,pages_read_engagement,pages_manage_posts,pages_manage_engagement"
)
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_OAUTH_REDIRECT_URI = os.getenv(
    "GOOGLE_OAUTH_REDIRECT_URI",
    f"{PUBLIC_BASE_URL}/auth/google/callback" if PUBLIC_BASE_URL else "",
)
GOOGLE_OAUTH_SCOPES = os.getenv(
    "GOOGLE_OAUTH_SCOPES",
    "https://www.googleapis.com/auth/analytics.readonly",
)
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
SESSION_SECRET = os.getenv("SESSION_SECRET", "change-this-in-production")
PORTAL_PATH = os.getenv("PORTAL_PATH", "/portal")
PORTAL_INVITE_SALT = os.getenv("PORTAL_INVITE_SALT", "portal-invite")
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "").strip().lower()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
GPT_OAUTH_CLIENT_ID = os.getenv("GPT_OAUTH_CLIENT_ID", "gpt_client_1")
GPT_OAUTH_CLIENT_SECRET = os.getenv("GPT_OAUTH_CLIENT_SECRET", "")

HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "90"))
DEFAULT_PAGE_LIMIT = int(os.getenv("DEFAULT_PAGE_LIMIT", "100"))
DEFAULT_MAX_PAGES = int(os.getenv("DEFAULT_MAX_PAGES", "20"))
ANALYSIS_PAGE_LIMIT = int(os.getenv("ANALYSIS_PAGE_LIMIT", "100"))
ANALYSIS_MAX_PAGES = int(os.getenv("ANALYSIS_MAX_PAGES", "3"))
ANALYSIS_DEFAULT_DATE_PRESET = os.getenv("ANALYSIS_DEFAULT_DATE_PRESET", "last_7d")
META_RETRY_MAX_ATTEMPTS = int(os.getenv("META_RETRY_MAX_ATTEMPTS", "4"))
META_RETRY_BASE_DELAY_SECONDS = float(os.getenv("META_RETRY_BASE_DELAY_SECONDS", "2.0"))
EXPORT_DIR = Path(os.getenv("EXPORT_DIR", "exports")).expanduser().resolve()
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
ALLOW_ORIGINS = _env_list("ALLOW_ORIGINS", "*")

if IS_PRODUCTION:
    missing = []
    if not PUBLIC_BASE_URL:
        missing.append("PUBLIC_BASE_URL")
    if SESSION_SECRET == "change-this-in-production":
        missing.append("SESSION_SECRET")
    if not GPT_OAUTH_CLIENT_SECRET:
        missing.append("GPT_OAUTH_CLIENT_SECRET")
    if "*" in ALLOW_ORIGINS:
        missing.append("ALLOW_ORIGINS")
    if missing:
        raise RuntimeError(
            "Production configuration is unsafe or incomplete: "
            + ", ".join(missing)
        )
