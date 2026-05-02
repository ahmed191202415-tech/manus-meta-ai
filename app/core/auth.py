from fastapi import HTTPException, Request

from app.core.meta_client import meta_call
from app.core.meta_context import set_current_meta_app_secret
from app.core.oauth_store import (
    find_meta_connection_by_access_token,
    get_active_meta_connection_for_tenant,
    get_app_token_data,
    get_tenant_account_by_id,
    get_tenant_meta_app,
    list_tenant_accounts,
    is_account_expired,
    purge_meta_connection,
)


def _clear_meta_session(request: Request):
    request.session.pop("meta_access_token", None)
    request.session.pop("meta_user_id", None)
    request.session.pop("meta_user", None)


def _is_invalid_meta_token_error(exc: HTTPException) -> bool:
    detail = exc.detail
    if isinstance(detail, dict):
        error_code = detail.get("code")
        message = str(detail.get("message") or "").lower()
        if error_code == 190:
            return True
        if "invalid oauth" in message or "session has expired" in message:
            return True
    return False


def _validate_meta_access_token(access_token: str, app_secret: str | None = None) -> dict:
    return meta_call("GET", "me", access_token, params={"fields": "id,name"}, app_secret=app_secret)


def _resolve_valid_saved_token(
    request: Request,
    access_token: str,
    meta_user_id: str | None,
    tenant_id: str | None,
    app_secret: str | None = None,
):
    try:
        me_data = _validate_meta_access_token(access_token, app_secret=app_secret)
    except HTTPException as exc:
        if _is_invalid_meta_token_error(exc):
            if meta_user_id:
                purge_meta_connection(meta_user_id, tenant_id=tenant_id)
            _clear_meta_session(request)
            raise HTTPException(
                status_code=401,
                detail="Meta connection expired or was revoked. Please authenticate again."
            ) from exc
        raise

    if meta_user_id and str(me_data.get("id") or "").strip() != str(meta_user_id).strip():
        purge_meta_connection(str(meta_user_id), tenant_id=tenant_id)
        _clear_meta_session(request)
        raise HTTPException(
            status_code=401,
            detail="Meta connection is no longer valid. Please authenticate again."
        )

    return access_token


def _resolve_default_saved_connection(request: Request) -> str | None:
    """Fallback for GPT Actions when ChatGPT does not send the OAuth bearer token.

    It uses the newest active tenant with a saved Meta connection. This keeps the
    old portal/Meta connection usable even if the GPT editor test call misses the
    Authorization header.
    """
    try:
        for account in list_tenant_accounts(include_deleted=False):
            status = str((account or {}).get("status") or "").lower()
            if status in {"disabled", "deleted"} or is_account_expired(account):
                continue
            tenant_id = account.get("tenant_id")
            if not tenant_id:
                continue
            connection = get_active_meta_connection_for_tenant(tenant_id)
            if not connection or not connection.get("meta_access_token"):
                continue
            meta_app = get_tenant_meta_app(tenant_id)
            app_secret = meta_app.get("meta_app_secret") if meta_app else None
            set_current_meta_app_secret(app_secret)
            request.session["tenant_id"] = tenant_id
            request.session["meta_access_token"] = connection["meta_access_token"]
            request.session["meta_user_id"] = connection.get("meta_user_id")
            request.session["meta_user"] = {
                "id": connection.get("meta_user_id"),
                "name": connection.get("meta_user_name"),
            }
            return _resolve_valid_saved_token(
                request,
                connection["meta_access_token"],
                connection.get("meta_user_id"),
                tenant_id,
                app_secret=app_secret,
            )
    except HTTPException:
        raise
    except Exception:
        return None
    return None


async def resolve_access_token(request: Request) -> str:
    tenant_id = request.session.get("tenant_id")
    if tenant_id:
        account = get_tenant_account_by_id(tenant_id)
        status = str((account or {}).get("status") or "").lower()
        if not account or account.get("deleted_at") or status in {"disabled", "deleted"} or is_account_expired(account):
            _clear_meta_session(request)
            request.session.pop("tenant_id", None)
            request.session.pop("user_email", None)
            raise HTTPException(status_code=403, detail="This email no longer has access.")

    query_token = request.query_params.get("access_token")
    if query_token:
        set_current_meta_app_secret(None)
        return query_token.strip()

    authorization = request.headers.get("authorization")
    if authorization and authorization.lower().startswith("bearer "):
        bearer = authorization.split(" ", 1)[1].strip()

        if not bearer:
            raise HTTPException(status_code=401, detail="Empty bearer token")

        app_token_data = get_app_token_data(bearer)
        if app_token_data:
            meta_access_token = app_token_data.get("meta_access_token")
            if meta_access_token:
                app_secret = app_token_data.get("meta_app_secret")
                set_current_meta_app_secret(app_secret)
                return _resolve_valid_saved_token(
                    request,
                    meta_access_token,
                    app_token_data.get("meta_user_id"),
                    app_token_data.get("tenant_id"),
                    app_secret=app_secret,
                )

        direct_conn = find_meta_connection_by_access_token(bearer)
        if direct_conn:
            tenant_id = direct_conn.get("tenant_id")
            meta_app = get_tenant_meta_app(tenant_id) if tenant_id else None
            set_current_meta_app_secret(meta_app.get("meta_app_secret") if meta_app else None)
        else:
            set_current_meta_app_secret(None)
        return bearer

    session_token = request.session.get("meta_access_token")
    if session_token:
        tenant_id = request.session.get("tenant_id")
        meta_app = get_tenant_meta_app(tenant_id) if tenant_id else None
        app_secret = meta_app.get("meta_app_secret") if meta_app else None
        set_current_meta_app_secret(app_secret)
        return _resolve_valid_saved_token(
            request,
            session_token,
            request.session.get("meta_user_id"),
            tenant_id,
            app_secret=app_secret,
        )

    tenant_id = request.session.get("tenant_id")
    if tenant_id:
        connection = get_active_meta_connection_for_tenant(tenant_id)
        meta_app = get_tenant_meta_app(tenant_id)
        if connection and meta_app:
            app_secret = meta_app.get("meta_app_secret")
            set_current_meta_app_secret(app_secret)
            request.session["meta_access_token"] = connection["meta_access_token"]
            request.session["meta_user_id"] = connection["meta_user_id"]
            request.session["meta_user"] = {
                "id": connection.get("meta_user_id"),
                "name": connection.get("meta_user_name"),
            }
            return _resolve_valid_saved_token(
                request,
                connection["meta_access_token"],
                connection.get("meta_user_id"),
                tenant_id,
                app_secret=app_secret,
            )

    default_token = _resolve_default_saved_connection(request)
    if default_token:
        return default_token

    raise HTTPException(
        status_code=401,
        detail="No access token found. Please authenticate first."
    )
