import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

import requests

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
PASSWORD_ITERATIONS = int(os.getenv("PASSWORD_ITERATIONS", "600000"))


def _headers(prefer: str = "resolution=merge-duplicates,return=representation"):
    return {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
        "Prefer": prefer,
    }


def _dt(dt):
    return dt.astimezone(timezone.utc).isoformat()


def _now_utc():
    return datetime.now(timezone.utc)


def _parse_dt(value):
    text = _clean(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _compute_subscription_dates(subscription_days: int | None):
    if not subscription_days:
        return None, None
    start = _now_utc()
    end = start + timedelta(days=int(subscription_days))
    return _dt(start), _dt(end)


def is_account_expired(account: dict | None) -> bool:
    if not account:
        return False
    expires_at = _parse_dt(account.get("access_expires_at"))
    if not expires_at:
        return False
    return expires_at < _now_utc()


def get_subscription_state(account: dict | None) -> dict:
    if not account:
        return {
            "has_subscription": False,
            "is_expired": False,
            "access_expires_at": None,
            "subscription_started_at": None,
        }
    return {
        "has_subscription": bool(account.get("access_expires_at")),
        "is_expired": is_account_expired(account),
        "access_expires_at": account.get("access_expires_at"),
        "subscription_started_at": account.get("subscription_started_at"),
    }


def _rest_url(table: str) -> str:
    return f"{SUPABASE_URL}/rest/v1/{table}"


def _raise_if_unconfigured():
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required.")


def _get_many(table: str, params: dict | None = None):
    _raise_if_unconfigured()
    r = requests.get(_rest_url(table), headers=_headers(), params=params or {}, timeout=30)
    r.raise_for_status()
    return r.json()


def _get_single(table: str, params: dict | None = None):
    rows = _get_many(table, params=params)
    return rows[0] if rows else None


def _post(table: str, payload: dict, params: dict | None = None, prefer: str = "resolution=merge-duplicates,return=representation"):
    _raise_if_unconfigured()
    r = requests.post(_rest_url(table), headers=_headers(prefer=prefer), params=params or {}, json=payload, timeout=30)
    r.raise_for_status()
    if r.text.strip():
        return r.json()
    return None


def _patch(table: str, params: dict, payload: dict, prefer: str = "return=representation"):
    _raise_if_unconfigured()
    r = requests.patch(_rest_url(table), headers=_headers(prefer=prefer), params=params, json=payload, timeout=30)
    r.raise_for_status()
    if r.text.strip():
        return r.json()
    return None


def _delete(table: str, params: dict):
    _raise_if_unconfigured()
    r = requests.delete(_rest_url(table), headers=_headers(prefer="return=minimal"), params=params, timeout=30)
    r.raise_for_status()
    return True


def _clean(value: str | None) -> str:
    return str(value or "").strip()


def normalize_email(email: str | None) -> str:
    return _clean(email).lower()


def tenant_id_from_email(email: str | None) -> str:
    return normalize_email(email)


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        _clean(password).encode("utf-8"),
        salt.encode("utf-8"),
        PASSWORD_ITERATIONS,
    ).hex()
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt}${digest}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations, salt, digest = password_hash.split("$", 3)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    candidate = hashlib.pbkdf2_hmac(
        "sha256",
        _clean(password).encode("utf-8"),
        salt.encode("utf-8"),
        int(iterations),
    ).hex()
    return secrets.compare_digest(candidate, digest)


def create_tenant_account(email: str, password: str, display_name: str | None = None):
    clean_email = _clean(email).lower()
    if not clean_email or not _clean(password):
        raise ValueError("Email and password are required.")

    existing = get_tenant_account_by_email(clean_email)
    if existing:
        raise ValueError("A dashboard account with this email already exists.")

    tenant_id = "tenant_" + secrets.token_urlsafe(12)
    now = _dt(datetime.now(timezone.utc))
    payload = {
        "tenant_id": tenant_id,
        "email": clean_email,
        "display_name": _clean(display_name) or clean_email,
        "password_hash": hash_password(password),
        "created_at": now,
        "updated_at": now,
    }
    rows = _post("tenant_accounts", payload, prefer="return=representation") or []
    return rows[0] if rows else payload


def ensure_invited_tenant(tenant_id: str, display_name: str | None = None, email: str | None = None):
    clean_tenant_id = _clean(tenant_id)
    if not clean_tenant_id:
        raise ValueError("tenant_id is required.")

    existing = get_tenant_account_by_id(clean_tenant_id)
    if existing:
        updates = {}
        clean_name = _clean(display_name)
        clean_email = _clean(email).lower()
        if clean_name and clean_name != _clean(existing.get("display_name")):
            updates["display_name"] = clean_name
        if clean_email and clean_email != _clean(existing.get("email")).lower():
            updates["email"] = clean_email
        if updates:
            updates["updated_at"] = _dt(datetime.now(timezone.utc))
            rows = _patch("tenant_accounts", params={"tenant_id": f"eq.{clean_tenant_id}"}, payload=updates) or []
            return rows[0] if rows else existing
        return existing

    now = _dt(datetime.now(timezone.utc))
    clean_email = _clean(email).lower() or f"{clean_tenant_id}@invited.local"
    payload = {
        "tenant_id": clean_tenant_id,
        "email": clean_email,
        "display_name": _clean(display_name) or clean_tenant_id,
        "password_hash": "invite_only",
        "created_at": now,
        "updated_at": now,
    }
    rows = _post("tenant_accounts", payload, prefer="return=representation") or []
    return rows[0] if rows else payload


def get_tenant_account_by_email(email: str):
    return _get_single(
        "tenant_accounts",
        params={"email": f"eq.{normalize_email(email)}", "select": "*", "limit": "1"},
    )


def get_tenant_account_by_id(tenant_id: str):
    return _get_single(
        "tenant_accounts",
        params={"tenant_id": f"eq.{_clean(tenant_id)}", "select": "*", "limit": "1"},
    )


def list_tenant_accounts(include_deleted: bool = False):
    params = {
        "select": "tenant_id,email,display_name,status,added_at,disabled_at,deleted_at,updated_at,subscription_started_at,access_expires_at",
        "order": "added_at.desc",
    }
    if not include_deleted:
        params["deleted_at"] = "is.null"
    items = _get_many("tenant_accounts", params=params)
    for item in items:
        item["subscription"] = get_subscription_state(item)
    return items


def upsert_access_email(email: str, display_name: str | None = None, status: str = "active", subscription_days: int | None = None):
    clean_email = normalize_email(email)
    if not clean_email:
        raise ValueError("Email is required.")
    if status not in {"active", "disabled"}:
        raise ValueError("Status must be active or disabled.")

    existing = get_tenant_account_by_email(clean_email)
    now = _dt(datetime.now(timezone.utc))
    tenant_id = tenant_id_from_email(clean_email)
    subscription_started_at, access_expires_at = _compute_subscription_dates(subscription_days)
    if existing:
        payload = {
            "display_name": _clean(display_name) or existing.get("display_name") or clean_email,
            "status": status,
            "disabled_at": now if status == "disabled" else None,
            "deleted_at": None,
            "updated_at": now,
        }
        if subscription_days:
            payload["subscription_started_at"] = subscription_started_at
            payload["access_expires_at"] = access_expires_at
        rows = _patch("tenant_accounts", params={"email": f"eq.{clean_email}"}, payload=payload) or []
        result = rows[0] if rows else existing
        result["subscription"] = get_subscription_state(result)
        return result

    payload = {
        "tenant_id": tenant_id,
        "email": clean_email,
        "display_name": _clean(display_name) or clean_email,
        "password_hash": "access_managed",
        "status": status,
        "added_at": now,
        "disabled_at": now if status == "disabled" else None,
        "deleted_at": None,
        "subscription_started_at": subscription_started_at,
        "access_expires_at": access_expires_at,
        "created_at": now,
        "updated_at": now,
    }
    rows = _post("tenant_accounts", payload, prefer="return=representation") or []
    result = rows[0] if rows else payload
    result["subscription"] = get_subscription_state(result)
    return result


def set_access_email_status(email: str, status: str, subscription_days: int | None = None):
    clean_email = normalize_email(email)
    if status not in {"active", "disabled"}:
        raise ValueError("Status must be active or disabled.")
    existing = get_tenant_account_by_email(clean_email)
    if not existing or existing.get("deleted_at"):
        raise ValueError("Email not found.")
    now = _dt(datetime.now(timezone.utc))
    payload = {
        "status": status,
        "disabled_at": now if status == "disabled" else None,
        "updated_at": now,
    }
    if subscription_days:
        subscription_started_at, access_expires_at = _compute_subscription_dates(subscription_days)
        payload["subscription_started_at"] = subscription_started_at
        payload["access_expires_at"] = access_expires_at
    rows = _patch(
        "tenant_accounts",
        params={"email": f"eq.{clean_email}"},
        payload=payload,
    ) or []
    result = rows[0] if rows else existing
    result["subscription"] = get_subscription_state(result)
    return result


def delete_access_email(email: str):
    clean_email = normalize_email(email)
    existing = get_tenant_account_by_email(clean_email)
    if not existing:
        raise ValueError("Email not found.")
    now = _dt(datetime.now(timezone.utc))
    rows = _patch(
        "tenant_accounts",
        params={"email": f"eq.{clean_email}"},
        payload={
            "status": "deleted",
            "deleted_at": now,
            "updated_at": now,
        },
    ) or []
    result = rows[0] if rows else existing
    result["subscription"] = get_subscription_state(result)
    return result


def ensure_allowed_tenant_by_email(email: str, display_name: str | None = None):
    clean_email = normalize_email(email)
    record = get_tenant_account_by_email(clean_email)
    if not record:
        raise ValueError("This email does not have access.")
    if record.get("deleted_at") or str(record.get("status") or "").lower() == "deleted":
        raise ValueError("This email was deleted from access.")
    if str(record.get("status") or "").lower() != "active":
        raise ValueError("This email is currently disabled.")
    if is_account_expired(record):
        raise ValueError("This subscription has expired.")

    if display_name and _clean(display_name) != _clean(record.get("display_name")):
        rows = _patch(
            "tenant_accounts",
            params={"email": f"eq.{clean_email}"},
            payload={"display_name": _clean(display_name), "updated_at": _dt(datetime.now(timezone.utc))},
        ) or []
        record = rows[0] if rows else record
    return record


def authenticate_tenant_account(email: str, password: str):
    account = get_tenant_account_by_email(email)
    if not account:
        return None
    if not verify_password(password, str(account.get("password_hash") or "")):
        return None
    return account


def update_tenant_meta_app(
    tenant_id: str,
    meta_app_id: str,
    meta_app_secret: str,
    meta_oauth_scopes: str | None = None,
    webhook_verify_token: str | None = None,
    webhook_callback_url: str | None = None,
):
    payload = {
        "tenant_id": _clean(tenant_id),
        "meta_app_id": _clean(meta_app_id),
        "meta_app_secret": _clean(meta_app_secret),
        "meta_oauth_scopes": _clean(meta_oauth_scopes),
        "webhook_verify_token": _clean(webhook_verify_token),
        "webhook_callback_url": _clean(webhook_callback_url),
        "updated_at": _dt(datetime.now(timezone.utc)),
    }
    params = {"on_conflict": "tenant_id"}
    rows = _post("tenant_meta_apps", payload, params=params, prefer="resolution=merge-duplicates,return=representation") or []
    return rows[0] if rows else payload


def get_tenant_meta_app(tenant_id: str):
    return _get_single(
        "tenant_meta_apps",
        params={"tenant_id": f"eq.{_clean(tenant_id)}", "select": "*", "limit": "1"},
    )


def get_tenant_meta_app_required(tenant_id: str):
    app = get_tenant_meta_app(tenant_id)
    if not app:
        raise ValueError("Meta app settings were not found for this tenant.")
    if not _clean(app.get("meta_app_id")) or not _clean(app.get("meta_app_secret")):
        raise ValueError("Meta app settings are incomplete for this tenant.")
    return app


def save_meta_connection(
    tenant_id: str,
    meta_user_id: str,
    meta_access_token: str,
    meta_user_name: str | None = None,
    granted_scopes: str | None = None,
):
    params = {"on_conflict": "tenant_id,meta_user_id"}
    payload = {
        "tenant_id": _clean(tenant_id),
        "meta_user_id": _clean(meta_user_id),
        "meta_user_name": _clean(meta_user_name),
        "meta_access_token": _clean(meta_access_token),
        "granted_scopes": _clean(granted_scopes),
        "updated_at": _dt(datetime.now(timezone.utc)),
    }
    rows = _post("meta_connections", payload, params=params, prefer="resolution=merge-duplicates,return=representation") or []
    return rows[0] if rows else payload


def get_meta_connection(meta_user_id: str, tenant_id: str | None = None):
    params = {
        "meta_user_id": f"eq.{_clean(meta_user_id)}",
        "select": "*",
        "limit": "1",
        "order": "updated_at.desc",
    }
    if tenant_id:
        params["tenant_id"] = f"eq.{_clean(tenant_id)}"
    return _get_single("meta_connections", params=params)


def get_latest_meta_connection():
    """Return newest saved Meta connection directly from meta_connections.

    Used as GPT fallback when no OAuth bearer/session is supplied.
    This avoids relying on tenant_accounts shape/status columns.
    """
    return _get_single(
        "meta_connections",
        params={
            "select": "*",
            "limit": "1",
            "order": "updated_at.desc",
        },
    )


def get_active_meta_connection_for_tenant(tenant_id: str):
    return _get_single(
        "meta_connections",
        params={
            "tenant_id": f"eq.{_clean(tenant_id)}",
            "select": "*",
            "limit": "1",
            "order": "updated_at.desc",
        },
    )


def find_meta_connection_by_access_token(access_token: str):
    return _get_single(
        "meta_connections",
        params={
            "meta_access_token": f"eq.{_clean(access_token)}",
            "select": "*",
            "limit": "1",
        },
    )


def set_selected_page(
    tenant_id: str,
    meta_user_id: str,
    page_id: str,
    page_name: str | None = None,
    page_access_token: str | None = None,
):
    rows = _patch(
        "meta_connections",
        params={
            "tenant_id": f"eq.{_clean(tenant_id)}",
            "meta_user_id": f"eq.{_clean(meta_user_id)}",
        },
        payload={
            "selected_page_id": _clean(page_id),
            "selected_page_name": _clean(page_name),
            "selected_page_access_token": _clean(page_access_token),
            "updated_at": _dt(datetime.now(timezone.utc)),
        },
    ) or []
    return rows[0] if rows else None


def delete_meta_connection(meta_user_id: str, tenant_id: str | None = None):
    params = {"meta_user_id": f"eq.{_clean(meta_user_id)}"}
    if tenant_id:
        params["tenant_id"] = f"eq.{_clean(tenant_id)}"
    return _delete("meta_connections", params)


def create_auth_code(tenant_id: str, meta_user_id: str, expires_in: int = 600):
    code = "code_" + secrets.token_urlsafe(24)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    payload = {
        "code": code,
        "tenant_id": _clean(tenant_id),
        "meta_user_id": _clean(meta_user_id),
        "expires_at": _dt(expires_at),
        "used": False,
    }
    _post("oauth_codes", payload, prefer="return=representation")
    return code


def consume_auth_code(code: str):
    row = _get_single(
        "oauth_codes",
        params={"code": f"eq.{_clean(code)}", "select": "*", "limit": "1"},
    )
    if not row or row.get("used"):
        return None

    expires_at = row.get("expires_at")
    if not expires_at:
        return None

    exp = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
    if exp < datetime.now(timezone.utc):
        return None

    _patch("oauth_codes", params={"code": f"eq.{_clean(code)}"}, payload={"used": True}, prefer="return=minimal")
    return row


def create_app_token(tenant_id: str, meta_user_id: str, expires_in: int = 86400):
    token = "app_" + secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    payload = {
        "app_token": token,
        "tenant_id": _clean(tenant_id),
        "meta_user_id": _clean(meta_user_id),
        "expires_at": _dt(expires_at),
    }
    _post("app_tokens", payload, prefer="return=representation")
    return token


def delete_app_tokens(meta_user_id: str | None = None, tenant_id: str | None = None):
    params = {}
    if meta_user_id:
        params["meta_user_id"] = f"eq.{_clean(meta_user_id)}"
    if tenant_id:
        params["tenant_id"] = f"eq.{_clean(tenant_id)}"
    if not params:
        return False
    _delete("app_tokens", params)
    return True


def purge_meta_connection(meta_user_id: str, tenant_id: str | None = None):
    delete_app_tokens(meta_user_id=meta_user_id, tenant_id=tenant_id)
    delete_meta_connection(meta_user_id=meta_user_id, tenant_id=tenant_id)
    return True


def get_app_token_data(token: str):
    row = _get_single(
        "app_tokens",
        params={"app_token": f"eq.{_clean(token)}", "select": "*", "limit": "1"},
    )
    if not row:
        return None

    exp = datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
    if exp < datetime.now(timezone.utc):
        return None

    account = get_tenant_account_by_id(row["tenant_id"])
    account_status = str((account or {}).get("status") or "").lower()
    if not account or account.get("deleted_at") or account_status in {"disabled", "deleted"} or is_account_expired(account):
        return None

    connection = get_meta_connection(row["meta_user_id"], tenant_id=row["tenant_id"])
    if not connection:
        return None

    meta_app = get_tenant_meta_app(row["tenant_id"])
    return {
        "tenant_id": row["tenant_id"],
        "meta_access_token": connection["meta_access_token"],
        "meta_user_id": connection["meta_user_id"],
        "meta_user_name": connection.get("meta_user_name"),
        "meta_app_id": meta_app.get("meta_app_id") if meta_app else None,
        "meta_app_secret": meta_app.get("meta_app_secret") if meta_app else None,
    }


def get_tenant_status(tenant_id: str):
    account = get_tenant_account_by_id(tenant_id)
    meta_app = get_tenant_meta_app(tenant_id)
    connection = get_active_meta_connection_for_tenant(tenant_id)
    return {
        "tenant_id": tenant_id,
        "account": {
            "email": account.get("email") if account else None,
            "display_name": account.get("display_name") if account else None,
            "status": account.get("status") if account else None,
            "subscription_started_at": account.get("subscription_started_at") if account else None,
            "access_expires_at": account.get("access_expires_at") if account else None,
            "subscription_expired": is_account_expired(account),
        },
        "meta_app": {
            "configured": bool(meta_app and _clean(meta_app.get("meta_app_id")) and _clean(meta_app.get("meta_app_secret"))),
            "meta_app_id": meta_app.get("meta_app_id") if meta_app else None,
            "webhook_callback_url": meta_app.get("webhook_callback_url") if meta_app else None,
            "webhook_verify_token_set": bool(_clean(meta_app.get("webhook_verify_token"))) if meta_app else False,
        },
        "meta_connection": {
            "connected": bool(connection),
            "meta_user_id": connection.get("meta_user_id") if connection else None,
            "meta_user_name": connection.get("meta_user_name") if connection else None,
            "selected_page_id": connection.get("selected_page_id") if connection else None,
            "selected_page_name": connection.get("selected_page_name") if connection else None,
        },
    }
