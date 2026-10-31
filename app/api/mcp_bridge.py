"""Authenticated, read-only MCP bridge for the existing Meta Ads backend.

The browser portal and OAuth storage are reused; this module does not expose
Meta credentials, Supabase credentials, or server-side tokens to MCP clients.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import (
    GPT_OAUTH_CLIENT_ID,
    GPT_OAUTH_CLIENT_SECRET,
    PUBLIC_BASE_URL,
    SESSION_SECRET,
)
from app.core.meta_client import meta_call
from app.core.oauth_store import consume_auth_code, create_app_token, get_app_token_data

router = APIRouter(tags=["mcp"])
BASE = (PUBLIC_BASE_URL or "https://app.allingpt.online").rstrip("/")
RESOURCE = BASE + "/mcp"
READ_SCOPE = "ads.read"
AUTH_CONTEXT_KEY = "mcp_oauth_context"


def _code_signer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(SESSION_SECRET, salt="mcp-pkce-code-v1")


def _redirect_allowed(value: str) -> bool:
    parsed = urlparse(value)
    return (
        parsed.scheme == "https"
        and parsed.hostname == "chatgpt.com"
        and (
            parsed.path.startswith("/connector/oauth/")
            or parsed.path == "/connector_platform_oauth_redirect"
        )
        and not parsed.username and not parsed.password
    )


def wrap_mcp_authorization_code(request: Request, code: str) -> str:
    """Wrap the one-time DB-backed code in signed, short-lived PKCE context."""
    context = request.session.get(AUTH_CONTEXT_KEY)
    if not isinstance(context, dict):
        return code
    request.session.pop(AUTH_CONTEXT_KEY, None)
    return _code_signer().dumps({
        "code": code,
        "challenge": context["challenge"],
        "client_id": context["client_id"],
        "redirect_uri": context["redirect_uri"],
        "resource": context["resource"],
    })


@router.get("/.well-known/oauth-protected-resource")
async def protected_resource_metadata():
    return {
        "resource": RESOURCE,
        "authorization_servers": [BASE],
        "scopes_supported": [READ_SCOPE],
        "bearer_methods_supported": ["header"],
    }


@router.get("/.well-known/oauth-authorization-server")
async def oauth_server_metadata():
    return {
        "issuer": BASE,
        "authorization_endpoint": BASE + "/mcp/authorize",
        "token_endpoint": BASE + "/mcp/token",
        "token_endpoint_auth_methods_supported": ["client_secret_post"],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256"],
        "scopes_supported": [READ_SCOPE],
    }


@router.get("/mcp/authorize")
async def mcp_authorize(
    request: Request,
    client_id: str,
    redirect_uri: str,
    response_type: str = "code",
    state: str = "",
    code_challenge: str = "",
    code_challenge_method: str = "",
    resource: str = "",
    scope: str = "",
):
    if not secrets.compare_digest(client_id, GPT_OAUTH_CLIENT_ID):
        raise HTTPException(status_code=400, detail="Unknown OAuth client")
    if response_type != "code" or not _redirect_allowed(redirect_uri):
        raise HTTPException(status_code=400, detail="Invalid OAuth redirect")
    if code_challenge_method != "S256" or not re.fullmatch(r"[A-Za-z0-9_\\-]{43,128}", code_challenge):
        raise HTTPException(status_code=400, detail="PKCE S256 is required")
    if resource and resource.rstrip("/") != RESOURCE:
        raise HTTPException(status_code=400, detail="Incorrect OAuth resource")
    if scope and any(s != READ_SCOPE for s in scope.split()):
        raise HTTPException(status_code=400, detail="Unsupported scope")

    request.session[AUTH_CONTEXT_KEY] = {
        "challenge": code_challenge,
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "resource": RESOURCE,
    }
    query = urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "state": state,
    })
    return RedirectResponse("/oauth/authorize?" + query, status_code=302)


@router.post("/mcp/token")
async def mcp_token(request: Request):
    form = await request.form()
    if form.get("grant_type") != "authorization_code":
        raise HTTPException(status_code=400, detail="Unsupported grant type")
    if not secrets.compare_digest(str(form.get("client_id", "")), GPT_OAUTH_CLIENT_ID):
        raise HTTPException(status_code=401, detail="Invalid client")
    if not secrets.compare_digest(str(form.get("client_secret", "")), GPT_OAUTH_CLIENT_SECRET):
        raise HTTPException(status_code=401, detail="Invalid client secret")
    value = str(form.get("code") or "")
    try:
        signed = _code_signer().loads(value, max_age=300)
    except (BadSignature, SignatureExpired):
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth code")
    if signed.get("client_id") != GPT_OAUTH_CLIENT_ID:
        raise HTTPException(status_code=400, detail="Invalid client")
    if signed.get("redirect_uri") != str(form.get("redirect_uri") or ""):
        raise HTTPException(status_code=400, detail="Invalid redirect URI")
    if form.get("resource") and str(form.get("resource")).rstrip("/") != RESOURCE:
        raise HTTPException(status_code=400, detail="Invalid resource")
    verifier = str(form.get("code_verifier") or "")
    if not re.fullmatch(r"[A-Za-z0-9_\\-]{43,128}", verifier):
        raise HTTPException(status_code=400, detail="PKCE verifier required")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
    if not secrets.compare_digest(challenge, str(signed.get("challenge") or "")):
        raise HTTPException(status_code=400, detail="Invalid PKCE verifier")
    record = consume_auth_code(str(signed.get("code") or ""))
    if not record:
        raise HTTPException(status_code=400, detail="Used or expired OAuth code")
    token = create_app_token(tenant_id=record["tenant_id"], meta_user_id=record["meta_user_id"])
    return JSONResponse({
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": 86400,
        "scope": READ_SCOPE,
    }, headers={"Cache-Control": "no-store"})


TOOLS = [
    {
        "name": "list_meta_ad_accounts",
        "title": "List Meta advertising accounts",
        "description": "List the current user's accessible Meta ad accounts with IDs, names, currencies, account status and time zones.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_meta_ad_insights",
        "title": "Get Meta Ads performance",
        "description": "Read Meta Ads spend, impressions, clicks, CTR, CPC and campaign results for an account. Use date_preset=today for today's results; do not invent missing metrics.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "Digits or act_<digits> from list_meta_ad_accounts"},
                "date_preset": {"type": "string", "enum": ["today", "yesterday", "last_7d", "last_30d"], "default": "today"},
                "level": {"type": "string", "enum": ["account", "campaign", "adset", "ad"], "default": "campaign"},
            },
            "required": ["account_id"],
            "additionalProperties": False,
        },
    },
]
for _tool in TOOLS:
    _tool["annotations"] = {"readOnlyHint": True, "openWorldHint": True}
    _tool["securitySchemes"] = [{"type": "oauth2", "scopes": [READ_SCOPE]}]


def _rpc_result(request_id, result):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _rpc_error(request_id, code: int, message: str):
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


@router.post("/mcp")
async def mcp_endpoint(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(_rpc_error(None, -32700, "Invalid JSON"), status_code=400)
    if not isinstance(body, dict):
        return JSONResponse(_rpc_error(None, -32600, "Invalid request"), status_code=400)
    method = body.get("method")
    rid = body.get("id")
    if method == "notifications/initialized":
        return Response(status_code=202)
    if method == "initialize":
        return JSONResponse(_rpc_result(rid, {
            "protocolVersion": "2025-03-26",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "super-ad-analysis", "version": "0.1.0"},
        }))
    if method == "ping":
        return JSONResponse(_rpc_result(rid, {}))
    if method == "tools/list":
        return JSONResponse(_rpc_result(rid, {"tools": TOOLS}))
    if method != "tools/call":
        return JSONResponse(_rpc_error(rid, -32601, "Unknown MCP method"))

    auth = request.headers.get("Authorization", "")
    bearer = auth.split(" ", 1)[1].strip() if auth.lower().startswith("bearer ") else ""
    token_data = None
    if bearer:
        try:
            token_data = get_app_token_data(bearer)
        except Exception:
            token_data = None
    if not token_data:
        return JSONResponse(
            _rpc_error(rid, -32001, "Authentication required"),
            status_code=401,
            headers={"WWW-Authenticate": f'Bearer resource_metadata="{BASE}/.well-known/oauth-protected-resource"'},
        )
    params = body.get("params") or {}
    tool_name = params.get("name")
    args = params.get("arguments") or {}
    try:
        if tool_name == "list_meta_ad_accounts":
            result = meta_call("GET", "me/adaccounts", token_data["meta_access_token"], params={
                "fields": "id,account_id,name,currency,account_status,timezone_name",
                "limit": 100,
            }, app_secret=token_data.get("meta_app_secret"))
        elif tool_name == "get_meta_ad_insights":
            account_id = str(args.get("account_id") or "")
            if not re.fullmatch(r"(?:act_)?[0-9]{3,25}", account_id):
                return JSONResponse(_rpc_error(rid, -32602, "Invalid account ID"))
            account_id = account_id if account_id.startswith("act_") else "act_" + account_id
            date_preset = str(args.get("date_preset") or "today")
            level = str(args.get("level") or "campaign")
            if date_preset not in {"today", "yesterday", "last_7d", "last_30d"} or level not in {"account", "campaign", "adset", "ad"}:
                return JSONResponse(_rpc_error(rid, -32602, "Unsupported date or level"))
            result = meta_call("GET", account_id + "/insights", token_data["meta_access_token"], params={
                "fields": "account_id,account_name,campaign_id,campaign_name,adset_id,adset_name,ad_id,ad_name,spend,impressions,clicks,ctr,cpc,cpm,actions,cost_per_action_type,date_start,date_stop",
                "date_preset": date_preset,
                "level": level,
                "limit": 100,
            }, app_secret=token_data.get("meta_app_secret"))
        else:
            return JSONResponse(_rpc_error(rid, -32601, "Unknown tool"))
        result_text = json.dumps(result, ensure_ascii=False, default=str)
        if len(result_text) > 48000:
            result_text = result_text[:48000] + "\\n[Output truncated; request a smaller scope]"
        return JSONResponse(_rpc_result(rid, {
            "content": [{"type": "text", "text": result_text}],
            "isError": False,
        }))
    except HTTPException as exc:
        return JSONResponse(_rpc_result(rid, {
            "content": [{"type": "text", "text": f"Meta Ads error: HTTP {exc.status_code}"}],
            "isError": True,
        }))
    except Exception:
        return JSONResponse(_rpc_result(rid, {
            "content": [{"type": "text", "text": "Could not query Meta Ads. Check the account connection."}],
            "isError": True,
        }))


@router.get("/mcp")
async def mcp_get():
    return Response(status_code=405, headers={"Allow": "POST"})
