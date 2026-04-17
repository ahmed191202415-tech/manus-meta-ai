from fastapi import APIRouter, Depends

from app.schemas.meta_requests import RawMetaRequest
from app.core.auth import resolve_access_token
from app.core.meta_client import meta_call

router = APIRouter(prefix="/meta", tags=["meta"])


@router.post("/request")
async def raw_meta_request(body: RawMetaRequest, token: str = Depends(resolve_access_token)):
    return meta_call(body.method, body.path, token, params=body.params, data=body.data)
