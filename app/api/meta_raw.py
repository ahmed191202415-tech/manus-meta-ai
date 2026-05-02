from fastapi import APIRouter, Depends

from app.schemas.meta_requests import RawMetaRequest
from app.core.auth import resolve_access_token
from app.core.meta_client import meta_call
from app.core.token_router import choose_token_for_meta_path

router = APIRouter(prefix="/meta", tags=["meta"])


@router.post(
    "/request",
    summary="Dynamic Meta Graph API request",
    description=(
        "Primary dynamic tool. Use this for any user question that needs live Meta data not covered exactly by a fixed endpoint. "
        "Build the Meta Graph path and params from the user's request, then call it directly. "
        "Examples: path='act_<ACCOUNT_ID>/campaigns' with fields='id,name,status,objective,updated_time'; "
        "path='act_<ACCOUNT_ID>/insights' with level='campaign' and filtering='[{\"field\":\"campaign.id\",\"operator\":\"IN\",\"value\":[\"<CAMPAIGN_ID>\"]}]'; "
        "path='<CAMPAIGN_ID>/adsets' or '<ADSET_ID>/ads' for structure discovery. "
        "Prefer this tool when the user asks generally in Arabic like: هات، اسحب، حلل، شوف، قارن، دور، آخر حملة، بيانات حملة."
    ),
)
async def raw_meta_request(body: RawMetaRequest, token: str = Depends(resolve_access_token)):
    effective_token = choose_token_for_meta_path(
        user_token=token,
        path=body.path,
        method=body.method,
        params=body.params,
        data=body.data,
    )
    return meta_call(body.method, body.path, effective_token, params=body.params, data=body.data)
