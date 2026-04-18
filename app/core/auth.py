from typing import Optional

from fastapi import HTTPException, Request

from app.core.oauth_store import get_app_token_data


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
                return meta_access_token

        # لو لم نجده في التخزين، اعتبره Meta access token مباشر
        return bearer

    # 3) session
    session_token = request.session.get("meta_access_token")
    if session_token:
        return session_token

    raise HTTPException(
        status_code=401,
        detail="No access token found. Please authenticate first."
    )