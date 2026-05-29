from typing import Optional, Dict, Any
import json
import hmac
import hashlib
import time
from fastapi import HTTPException

from app.config import (
    META_API_VERSION,
    META_GRAPH_BASE,
    HTTP_TIMEOUT,
    META_RETRY_MAX_ATTEMPTS,
    META_RETRY_BASE_DELAY_SECONDS,
)
from app.core.http_client import SESSION
from app.core.meta_context import get_current_meta_app_secret


def normalize_account_id(account_id: str) -> str:
    account_id = str(account_id).strip()
    if account_id.startswith("act_"):
        return account_id
    if account_id.isdigit():
        return f"act_{account_id}"
    return account_id


def build_meta_url(path: str) -> str:
    clean_path = path.strip().lstrip("/")
    if not clean_path:
        raise HTTPException(status_code=400, detail="Empty Meta path is not allowed.")
    if clean_path.startswith("http://") or clean_path.startswith("https://"):
        raise HTTPException(status_code=400, detail="Pass a Meta Graph path only, not a full URL.")
    return f"{META_GRAPH_BASE}/{META_API_VERSION}/{clean_path}"


def appsecret_proof(access_token: str, app_secret: Optional[str] = None) -> Optional[str]:
    secret = (app_secret or get_current_meta_app_secret() or "").strip()
    if not secret:
        return None
    return hmac.new(
        secret.encode("utf-8"),
        msg=access_token.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()


def normalize_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return value


def normalize_payload(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    payload = payload or {}
    normalized: Dict[str, Any] = {}
    for key, value in payload.items():
        if value is None:
            continue
        normalized[key] = normalize_value(value)
    return normalized


def _is_retryable_meta_error(status_code: int, payload: Dict[str, Any]) -> bool:
    error = payload.get("error", payload) if isinstance(payload, dict) else {}
    if not isinstance(error, dict):
        return False
    code = error.get("code")
    subcode = error.get("error_subcode")
    message = str(error.get("message") or "").lower()
    if error.get("is_transient") is True:
        return True
    if status_code in {429, 500, 502, 503, 504}:
        return True
    if code in {4, 17, 32, 341, 613, 80004}:
        return True
    if subcode in {1504022}:
        return True
    return "request limit" in message or "too many" in message


def meta_call(
    method: str,
    path: str,
    access_token: str,
    params: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
    app_secret: Optional[str] = None,
) -> Dict[str, Any]:
    url = build_meta_url(path)
    headers = {"Authorization": f"Bearer {access_token}"}
    params = normalize_payload(params)
    data = normalize_payload(data)
    proof = appsecret_proof(access_token, app_secret=app_secret)
    if proof:
        params["appsecret_proof"] = proof
    last_network_error: Exception | None = None
    for attempt in range(1, META_RETRY_MAX_ATTEMPTS + 1):
        try:
            response = SESSION.request(
                method=method.upper(),
                url=url,
                headers=headers,
                params=params,
                data=data,
                timeout=HTTP_TIMEOUT,
            )
        except Exception as exc:
            last_network_error = exc
            if attempt < META_RETRY_MAX_ATTEMPTS:
                time.sleep(META_RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1)))
                continue
            raise HTTPException(status_code=502, detail=f"Meta request failed: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise HTTPException(status_code=502, detail=response.text) from exc

        if response.status_code < 400 and "error" not in payload:
            return payload

        if attempt < META_RETRY_MAX_ATTEMPTS and _is_retryable_meta_error(response.status_code, payload):
            time.sleep(META_RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1)))
            continue

        error = payload.get("error", payload)
        raise HTTPException(
            status_code=response.status_code if response.status_code >= 400 else 400,
            detail={
                "message": error.get("message", "Meta API error"),
                "type": error.get("type"),
                "code": error.get("code"),
                "error_subcode": error.get("error_subcode"),
                "fbtrace_id": error.get("fbtrace_id"),
                "raw": payload,
            },
        )

    if last_network_error is not None:
        raise HTTPException(status_code=502, detail=f"Meta request failed: {last_network_error}") from last_network_error
    raise HTTPException(status_code=502, detail="Meta request failed.")
