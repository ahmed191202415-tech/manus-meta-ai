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
    connection = get_active_google_connection_for_tenant(tenant_id)
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
    if manager_id:
        config["login_customer_id"] = _safe_customer_id(manager_id)
    try:
        return GoogleAdsClient.load_from_dict(config)
    except (ValueError, TypeError, KeyError):
        raise HTTPException(502, "Could not initialize official Google Ads SDK with the saved OAuth connection.")


def sdk_search(tenant_id: str, customer_id: str, query: str, *, manager_id=None, limit=250) -> dict:
    """Read from official client library; never run mutations."""
    cid = _safe_customer_id(customer_id)
    text = str(query or "").strip()
    if not re.match(r"(?is)^SELECT\\s+", text) or len(text) > 6500 or any(bad in text for bad in (";", "--", "/*")):
        raise HTTPException(422, "Only a single read-only GAQL SELECT statement is allowed.")
    max_rows = min(max(1, int(limit)), _MAX_ROWS)
    from google.protobuf.json_format import MessageToDict
    client = official_client_for_tenant(tenant_id, manager_id=manager_id)
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
        return {"rows": rows, "count": len(rows), "truncated": truncated, "client": "google-ads-python", "api_version": _GOOGLE_ADS_VERSION}
    except HTTPException:
        raise
    except Exception as exc:
        # SDK exceptions may contain request headers and response details.
        # Surface only validated provider-specific enum names; no tokens or raw text.
        err_code = "UNSPECIFIED"
        try:
            failures = getattr(getattr(exc, "failure", None), "errors", None) or []
            for failure in failures:
                for _, value in failure.error_code._pb.ListFields():
                    raw = str(getattr(value, "name", value))
                    if re.fullmatch(r"[A-Z][A-Z0-9_]{2,80}", raw):
                        err_code = raw
                        break
                if err_code != "UNSPECIFIED":
                    break
        except Exception:
            pass
        raise HTTPException(502, {
            "origin": "google_ads_official_sdk",
            "google_ads_error_code": err_code,
            "message": "Google Ads SDK search failed; no changes were made.",
            "next_step": "Check SDK query fields and Google Ads access for this account.",
        })
