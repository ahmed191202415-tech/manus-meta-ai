import secrets
import time

AUTH_CODES = {}
APP_TOKENS = {}

def create_auth_code(meta_access_token: str, meta_user: dict | None = None, expires_in: int = 600):
    code = "code_" + secrets.token_urlsafe(24)
    AUTH_CODES[code] = {
        "meta_access_token": meta_access_token,
        "meta_user": meta_user or {},
        "expires_at": time.time() + expires_in,
        "used": False,
    }
    return code

def consume_auth_code(code: str):
    item = AUTH_CODES.get(code)
    if not item:
        return None
    if item.get("used"):
        return None
    if item.get("expires_at", 0) < time.time():
        return None
    item["used"] = True
    return item

def create_app_token(meta_access_token: str, meta_user: dict | None = None, expires_in: int = 86400):
    token = "app_" + secrets.token_urlsafe(32)
    APP_TOKENS[token] = {
        "meta_access_token": meta_access_token,
        "meta_user": meta_user or {},
        "expires_at": time.time() + expires_in,
    }
    return token

def get_app_token_data(token: str):
    item = APP_TOKENS.get(token)
    if not item:
        return None
    if item.get("expires_at", 0) < time.time():
        return None
    return item
