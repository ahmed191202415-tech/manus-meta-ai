import os
import secrets
from datetime import datetime, timedelta, timezone
import requests

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

def _headers():
    return {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=representation",
    }

def _dt(dt):
    return dt.astimezone(timezone.utc).isoformat()

def save_meta_connection(meta_user_id: str, meta_access_token: str, meta_user_name: str | None = None):
    url = f"{SUPABASE_URL}/rest/v1/meta_connections"
    payload = {
        "meta_user_id": meta_user_id,
        "meta_user_name": meta_user_name,
        "meta_access_token": meta_access_token,
        "updated_at": _dt(datetime.now(timezone.utc)),
    }
    params = {"on_conflict": "meta_user_id"}
    r = requests.post(url, headers=_headers(), params=params, json=payload, timeout=30)
    r.raise_for_status()
    return True

def get_meta_connection(meta_user_id: str):
    url = f"{SUPABASE_URL}/rest/v1/meta_connections"
    params = {
        "meta_user_id": f"eq.{meta_user_id}",
        "select": "*",
        "limit": "1",
    }
    r = requests.get(url, headers=_headers(), params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data[0] if data else None

def create_auth_code(meta_user_id: str, expires_in: int = 600):
    code = "code_" + secrets.token_urlsafe(24)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    url = f"{SUPABASE_URL}/rest/v1/oauth_codes"
    payload = {
        "code": code,
        "meta_user_id": meta_user_id,
        "expires_at": _dt(expires_at),
        "used": False,
    }
    r = requests.post(url, headers=_headers(), json=payload, timeout=30)
    r.raise_for_status()
    return code

def consume_auth_code(code: str):
    url = f"{SUPABASE_URL}/rest/v1/oauth_codes"
    params = {
        "code": f"eq.{code}",
        "select": "*",
        "limit": "1",
    }
    r = requests.get(url, headers=_headers(), params=params, timeout=30)
    r.raise_for_status()
    rows = r.json()
    if not rows:
        return None

    row = rows[0]

    if row.get("used"):
        return None

    expires_at = row.get("expires_at")
    if not expires_at:
        return None

    exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    if exp < datetime.now(timezone.utc):
        return None

    patch_params = {"code": f"eq.{code}"}
    patch_payload = {"used": True}
    p = requests.patch(url, headers=_headers(), params=patch_params, json=patch_payload, timeout=30)
    p.raise_for_status()

    return row

def create_app_token(meta_user_id: str, expires_in: int = 86400):
    token = "app_" + secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    url = f"{SUPABASE_URL}/rest/v1/app_tokens"
    payload = {
        "app_token": token,
        "meta_user_id": meta_user_id,
        "expires_at": _dt(expires_at),
    }
    r = requests.post(url, headers=_headers(), json=payload, timeout=30)
    r.raise_for_status()
    return token

def get_app_token_data(token: str):
    url = f"{SUPABASE_URL}/rest/v1/app_tokens"
    params = {
        "app_token": f"eq.{token}",
        "select": "*",
        "limit": "1",
    }
    r = requests.get(url, headers=_headers(), params=params, timeout=30)
    r.raise_for_status()
    rows = r.json()
    if not rows:
        return None

    row = rows[0]
    exp = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
    if exp < datetime.now(timezone.utc):
        return None

    conn = get_meta_connection(row["meta_user_id"])
    if not conn:
        return None

    return {
        "meta_access_token": conn["meta_access_token"],
        "meta_user_id": conn["meta_user_id"],
        "meta_user_name": conn.get("meta_user_name"),
    }
