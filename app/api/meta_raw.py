from fastapi import APIRouter, Depends, HTTPException

from app.schemas.meta_requests import RawMetaRequest, ReadOnlyMetaQueryRequest
from app.core.auth import resolve_access_token
from app.core.meta_client import meta_call
from app.core.token_router import choose_token_for_meta_path

router = APIRouter(prefix="/meta", tags=["meta"])


@router.post("/query")
async def read_only_meta_query(body: ReadOnlyMetaQueryRequest, token: str = Depends(resolve_access_token)):
    try:
        return {
            "ok": True,
            "path": body.path,
            "data": meta_call("GET", body.path, token, params=body.params),
        }
    except HTTPException as exc:
        return {
            "ok": False,
            "path": body.path,
            "error": exc.detail,
            "next_step": (
                "Inspect this Meta Graph error. If the path is an insights edge, retry only after correcting "
                "the rejected token, permission, field, or parameter. Do not repeat the same request unchanged."
            ),
        }


@router.post("/request")
async def raw_meta_request(body: RawMetaRequest, token: str = Depends(resolve_access_token)):
    effective_token = choose_token_for_meta_path(
        user_token=token,
        path=body.path,
        method=body.method,
        params=body.params,
        data=body.data,
    )
    return meta_call(body.method, body.path, effective_token, params=body.params, data=body.data)
