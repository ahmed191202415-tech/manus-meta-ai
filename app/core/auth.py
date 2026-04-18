from fastapi import HTTPException, Request

from app.core.meta_client import meta_call
from app.core.oauth_store import get_app_token_data, purge_meta_connection


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


def _validate_meta_access_token(access_token: str) -> dict:
    return meta_call("GET", "me", access_token, params={"fields": "id,name"})


def _resolve_valid_saved_token(request: Request, access_token: str, meta_user_id: str | None):
    try:
        me_data = _validate_meta_access_token(access_token)
    except HTTPException as exc:
        if _is_invalid_meta_token_error(exc):
            if meta_user_id:
                purge_meta_connection(meta_user_id)
            _clear_meta_session(request)
            raise HTTPException(
                status_code=401,
                detail="Meta connection expired or was revoked. Please authenticate again."
            ) from exc
        raise

    if meta_user_id and str(me_data.get("id") or "").strip() != str(meta_user_id).strip():
        purge_meta_connection(meta_user_id)
        _clear_meta_session(request)
        raise HTTPException(
            status_code=401,
            detail="Meta connection is no longer valid. Please authenticate again."
        )

    return access_token


async def resolve_access_token(request: Request) -> str:
    """
    يرجع Meta access token الحقيقي من واحد من المصادر التالية بالترتيب:
    1) query param اسمه access_token (لو أُرسل مباشرة)
    2) Authorization: Bearer <token>
       - لو كان App Token داخلي من GPT OAuth -> نقرأ منه meta_access_token
       - لو لم نجده في التخزين -> نعتبره Meta token مباشر
    3) session["meta_access_token"]

    مهم:
    - لا نقرأ آخر توكن من Supabase بشكل عام
    - لا نستخدم Header() أو Query() هنا لأن هذه helper function وليست endpoint dependency
    """

    # 1) access_token من query string
    query_token = request.query_params.get("access_token")
    if query_token:
        return query_token.strip()

    # 2) Authorization header
    authorization = request.headers.get("authorization")
    if authorization and authorization.lower().startswith("bearer "):
        bearer = authorization.split(" ", 1)[1].strip()

        if not bearer:
            raise HTTPException(status_code=401, detail="Empty bearer token")

        # جرّب أولًا: هل هذا app token داخلي صادر من /oauth/token ؟
        app_token_data = get_app_token_data(bearer)
        if app_token_data:
            meta_access_token = app_token_data.get("meta_access_token")
            if meta_access_token:
                return _resolve_valid_saved_token(
                    request,
                    meta_access_token,
                    app_token_data.get("meta_user_id"),
                )

        # لو لم نجده في التخزين، اعتبره Meta access token مباشر
        return bearer

    # 3) session
    session_token = request.session.get("meta_access_token")
    if session_token:
        return _resolve_valid_saved_token(
            request,
            session_token,
            request.session.get("meta_user_id"),
        )

    raise HTTPException(
        status_code=401,
        detail="No access token found. Please authenticate first."
    )
