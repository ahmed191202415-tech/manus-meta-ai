from fastapi import HTTPException

from app.core.meta_client import meta_call
from app.core.oauth_store import (
    get_active_meta_connection_for_tenant,
    get_tenant_account_by_id,
    get_tenant_meta_app,
    is_account_expired,
)


def _safe_str(value: object) -> str:
    return str(value or "").strip()


def _base_result(tenant_id: str, display_name: str | None = None) -> dict:
    return {
        "tenant_id": tenant_id,
        "display_name": display_name or tenant_id,
        "state": "unknown",
        "reason": "unclassified",
        "next_action": "show_setup",
        "message_for_user": "نحتاج مراجعة حالة الربط.",
        "meta_app": {
            "configured": False,
            "meta_app_id": None,
        },
        "connection": {
            "connected": False,
            "meta_user_id": None,
            "meta_user_name": None,
        },
    }


def _classify_meta_exception(exc: HTTPException) -> tuple[str, str, str]:
    detail = exc.detail
    if isinstance(detail, dict):
        code = detail.get("code")
        subcode = detail.get("error_subcode")
        message = _safe_str(detail.get("message")).lower()

        if code == 190:
            return (
                "needs_reconnect",
                "token_invalid_or_expired",
                "show_reconnect",
            )
        if code == 191:
            return (
                "needs_app_review",
                "app_not_authorized",
                "show_support",
            )
        if code in {10, 200}:
            return (
                "needs_permissions",
                "permissions_missing",
                "show_reconnect",
            )
        if "redirect_uri" in message or "redirect uri" in message:
            return (
                "needs_app_fix",
                "redirect_uri_mismatch",
                "show_setup",
            )
        if "invalid oauth" in message or "session has expired" in message:
            return (
                "needs_reconnect",
                "token_invalid_or_expired",
                "show_reconnect",
            )
        if subcode == 458:
            return (
                "needs_reconnect",
                "user_revoked_access",
                "show_reconnect",
            )

    return (
        "needs_support",
        "unknown_meta_error",
        "show_support",
    )


def resolve_tenant_connection_state(tenant_id: str) -> dict:
    account = get_tenant_account_by_id(tenant_id)
    display_name = _safe_str((account or {}).get("display_name")) or tenant_id
    result = _base_result(tenant_id, display_name=display_name)

    if not account:
        result["state"] = "needs_identity"
        result["reason"] = "missing_account"
        result["next_action"] = "show_email_gate"
        result["message_for_user"] = "ادخل بريدك الإلكتروني المسموح له بالوصول للمتابعة."
        return result

    account_status = _safe_str(account.get("status")).lower() or "active"
    if account.get("deleted_at") or account_status == "deleted":
        result["state"] = "blocked"
        result["reason"] = "access_deleted"
        result["next_action"] = "show_blocked"
        result["message_for_user"] = "تم حذف هذا البريد من قائمة الوصول."
        return result
    if account_status != "active":
        result["state"] = "blocked"
        result["reason"] = "access_disabled"
        result["next_action"] = "show_blocked"
        result["message_for_user"] = "هذا البريد موقوف حاليًا. تواصل مع الإدارة لإعادة التفعيل."
        return result
    if is_account_expired(account):
        result["state"] = "blocked"
        result["reason"] = "subscription_expired"
        result["next_action"] = "show_blocked"
        result["message_for_user"] = "انتهت مدة الاشتراك الحالية. تواصل مع الإدارة لتجديد التفعيل."
        return result

    meta_app = get_tenant_meta_app(tenant_id)
    if meta_app:
        result["meta_app"] = {
            "configured": bool(_safe_str(meta_app.get("meta_app_id")) and _safe_str(meta_app.get("meta_app_secret"))),
            "meta_app_id": meta_app.get("meta_app_id"),
            "meta_oauth_scopes": meta_app.get("meta_oauth_scopes"),
        }

    connection = get_active_meta_connection_for_tenant(tenant_id)
    is_manual_token = bool(connection and connection.get("connection_mode") == "manual_token")

    if not result["meta_app"]["configured"] and not is_manual_token:
        result["state"] = "needs_setup"
        result["reason"] = "missing_meta_app_config"
        result["next_action"] = "show_setup"
        result["message_for_user"] = "أدخل بيانات تطبيق Meta أولًا ثم أعد المحاولة."
        return result

    if not connection:
        result["state"] = "needs_reconnect"
        result["reason"] = "missing_meta_connection"
        result["next_action"] = "show_reconnect"
        result["message_for_user"] = "بيانات التطبيق محفوظة. الخطوة التالية هي ربط حساب Meta."
        return result

    result["connection"] = {
        "connected": True,
        "meta_user_id": connection.get("meta_user_id"),
        "meta_user_name": connection.get("meta_user_name"),
        "connection_mode": connection.get("connection_mode") or "oauth",
    }

    try:
        me = meta_call(
            "GET",
            "me",
            connection["meta_access_token"],
            params={"fields": "id,name"},
            app_secret=meta_app.get("meta_app_secret") if meta_app and not is_manual_token else None,
        )
        resolved_user_id = _safe_str(me.get("id"))
        saved_user_id = _safe_str(connection.get("meta_user_id"))
        if saved_user_id and resolved_user_id and saved_user_id != resolved_user_id:
            result["state"] = "needs_reconnect"
            result["reason"] = "meta_user_changed"
            result["next_action"] = "show_reconnect"
            result["message_for_user"] = "تم اكتشاف تغيير في الحساب المتصل. أعد ربط Meta."
            result["connection"]["connected"] = False
            return result

        result["state"] = "ready"
        result["reason"] = "connection_ok"
        result["next_action"] = "continue"
        result["message_for_user"] = "الربط جاهز ويمكن متابعة الاستخدام مباشرة."
        result["connection"]["meta_user_id"] = me.get("id")
        result["connection"]["meta_user_name"] = me.get("name")
        return result
    except HTTPException as exc:
        state, reason, next_action = _classify_meta_exception(exc)
        result["state"] = state
        result["reason"] = reason
        result["next_action"] = next_action
        result["connection"]["connected"] = False

        message_map = {
            "token_invalid_or_expired": "تم انتهاء أو إلغاء صلاحية الربط. أعد ربط Meta فقط.",
            "permissions_missing": "الربط موجود لكن الصلاحيات الحالية غير كافية. أعد الربط وتأكد من منح الصلاحيات المطلوبة.",
            "redirect_uri_mismatch": "إعدادات Redirect URI داخل Meta App غير مطابقة. راجع خطوة إعداد التطبيق.",
            "app_not_authorized": "تطبيق Meta الحالي غير مسموح له بهذه العملية. راجع إعدادات المراجعة أو وضع التطبيق.",
            "user_revoked_access": "تم إلغاء الوصول من داخل Meta. أعد الربط مرة أخرى.",
            "unknown_meta_error": "حدثت مشكلة غير متوقعة أثناء التحقق من الربط. حاول مرة أخرى أو تواصل مع الدعم.",
        }
        result["message_for_user"] = message_map.get(reason, "نحتاج إلى إعادة التحقق من حالة الربط.")
        return result
