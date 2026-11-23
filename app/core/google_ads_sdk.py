"""Tenant-scoped Google Ads SDK (official google-ads Python client, v26).

This adapter intentionally uses the EXISTING tenant OAuth connection; no user
credential strings are accepted in GPT commands and no secrets are logged.
It is opt-in for new read-only actions; existing Meta/Ads API routes stay intact.
"""
from __future__ import annotations

import os
import re
from fastapi import HTTPException

from app.config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
from app.core.oauth_store import get_active_google_connection_for_tenant
from app.core.google_ads_errors import error_category, next_step_for_error, safe_request_id

_GOOGLE_ADS_VERSION = "v26"
_MAX_ROWS = 250
_CID = re.compile(r"^[0-9]{10}$")


def _safe_customer_id(value) -> str:
    cid = str(value or "").replace("-", "").strip()
    if not _CID.fullmatch(cid):
        raise HTTPException(422, "Google Ads customer_id must contain exactly ten digits.")
    return cid


def official_client_for_tenant(tenant_id: str, manager_id: str | None = None):
    # Never use YAML or environment-wide refresh tokens for a multi-tenant server.
    try:
        connection = get_active_google_connection_for_tenant(tenant_id)
    except Exception:
        raise HTTPException(503, "Google connection database is unavailable.") from None
    if not connection or connection.get("connection_mode") != "oauth":
        raise HTTPException(409, "Connect Google Ads OAuth for this tenant first.")
    scopes = set(str(connection.get("scopes") or "").split())
    if "https://www.googleapis.com/auth/adwords" not in scopes:
        raise HTTPException(409, "This Google connection has not granted the Google Ads OAuth scope.")
    refresh_token = str(connection.get("refresh_token") or "")
    if not (refresh_token and GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET):
        raise HTTPException(409, "Google Ads OAuth refresh configuration is incomplete.")
    try:
        from google.ads.googleads.client import GoogleAdsClient
    except ImportError:
        raise HTTPException(503, {
            "code": "OFFICIAL_GOOGLE_ADS_SDK_NOT_INSTALLED",
            "message": "Install the pinned google-ads dependency before using SDK actions.",
        })
    config = {
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "refresh_token": refresh_token,
        "use_proto_plus": True,
    }
    # Since September 2026 developer tokens are optional. Do not add a dummy value.
    legacy = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN", "").strip()
    if legacy:
        config["developer_token"] = legacy
    login_customer_id = manager_id or os.getenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID")
    if login_customer_id:
        config["login_customer_id"] = _safe_customer_id(login_customer_id)
    try:
        return GoogleAdsClient.load_from_dict(config)
    except (ValueError, TypeError, KeyError):
        raise HTTPException(502, "Could not initialize official Google Ads SDK with the saved OAuth connection.")



def _sdk_failure(exc: Exception) -> tuple[int, dict]:
    """Decode protobuf enums using descriptors, without exposing provider text.

    ListFields() on the underlying protobuf returns integer enum values. Turning
    those integers into strings discarded the actual error for every SDK call.
    """
    code = "UNSPECIFIED"
    category = "unknown"
    family = None
    field_path = None
    try:
        failures = getattr(getattr(exc, "failure", None), "errors", None) or []
        for failure in failures:
            error_code = getattr(failure, "error_code", None)
            protobuf = getattr(error_code, "_pb", error_code)
            if protobuf is None:
                continue
            for descriptor, value in protobuf.ListFields():
                enum_type = getattr(descriptor, "enum_type", None)
                if enum_type is None:
                    continue
                member = enum_type.values_by_number.get(int(value))
                candidate = getattr(member, "name", "")
                if not re.fullmatch(r"[A-Z][A-Z0-9_]{2,79}", candidate):
                    continue
                # A later concrete error is more useful than UNSPECIFIED/UNKNOWN.
                if candidate in {"UNSPECIFIED", "UNKNOWN"}:
                    continue
                code = candidate
                family = getattr(descriptor, "json_name", "")
                if not isinstance(family, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", family):
                    family = None
                category = error_category(family or "", code)
                location = getattr(failure, "location", None)
                elements = getattr(location, "field_path_elements", None) or []
                parts = []
                for entry in elements[:6]:
                    name = getattr(entry, "field_name", "")
                    if isinstance(name, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,59}", name):
                        parts.append(name)
                field_path = ".".join(parts)[:150] or None
                break
            if code != "UNSPECIFIED":
                break
    except (AttributeError, TypeError, ValueError, KeyError):
        # Malformed details must never leak raw SDK exception strings.
        pass
    request_id = safe_request_id(getattr(exc, "request_id", None))
    status = "UNKNOWN"
    try:
        grpc_error = getattr(exc, "error", exc)
        grpc_status = grpc_error.code()
        candidate = getattr(grpc_status, "name", "")
        if isinstance(candidate, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{2,79}", candidate):
            status = candidate
    except (AttributeError, TypeError, ValueError):
        pass
    http_status = {
        "INVALID_ARGUMENT": 400, "UNAUTHENTICATED": 401,
        "PERMISSION_DENIED": 403, "NOT_FOUND": 404,
        "RESOURCE_EXHAUSTED": 429, "DEADLINE_EXCEEDED": 504,
        "UNAVAILABLE": 503,
    }.get(status, 502)
    return http_status, {
        "origin": "google_ads_official_sdk",
        "http_status": http_status,
        "api_status": status,
        "google_ads_error_code": code,
        "google_ads_error_category": category,
        "google_ads_error_family": family,
        "google_ads_error_field": field_path,
        "google_request_id": request_id,
        "api_version": _GOOGLE_ADS_VERSION,
        "message": "Google Ads SDK search failed; no changes were made.",
        "retryable": http_status in {429, 500, 502, 503, 504},
        "next_step": next_step_for_error(category, code),
    }


def sdk_search(tenant_id: str, customer_id: str, query: str, *, manager_id=None, limit=250) -> dict:
    """Read from the official client library; never run mutations."""
    cid = _safe_customer_id(customer_id)
    text = str(query or "").strip()
    if not re.match(r"(?is)^SELECT\s+", text) or len(text) > 6500 or any(bad in text for bad in (";", "--", "/*")):
        raise HTTPException(422, "Only a single read-only GAQL SELECT statement is allowed.")
    if isinstance(limit, bool) or not re.fullmatch(r"[0-9]{1,6}", str(limit)) or int(limit) < 1:
        raise HTTPException(422, "limit must be a positive integer.")
    max_rows = min(int(limit), _MAX_ROWS)
    client = official_client_for_tenant(tenant_id, manager_id=manager_id)
    from google.protobuf.json_format import MessageToDict
    try:
        service = client.get_service("GoogleAdsService", version=_GOOGLE_ADS_VERSION)
        iterator = service.search(customer_id=cid, query=text)
        rows = []
        truncated = False
        for row in iterator:
            if len(rows) >= max_rows:
                truncated = True
                break
            rows.append(MessageToDict(row._pb, preserving_proto_field_name=False))
        return {
            "rows": rows, "count": len(rows), "truncated": truncated,
            "client": "google-ads-python", "api_version": _GOOGLE_ADS_VERSION,
            "source": "Google Ads API", "query_method": "GoogleAdsService.Search",
            "verified_by_google_api": True, "google_api_called": True,
        }
    except HTTPException:
        raise
    except Exception as exc:
        # Never send SDK messages/headers or credentials to the Action response.
        status, detail = _sdk_failure(exc)
        raise HTTPException(status, detail) from None
