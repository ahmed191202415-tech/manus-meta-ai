"""Decode Google Ads REST failures without disclosing provider text or credentials.

Search returns an object and SearchStream can return an array containing an
error. GoogleAdsFailure and google.rpc.ErrorInfo are both useful diagnostics.
Only bounded symbolic codes, field paths and request IDs cross this boundary.
"""
from __future__ import annotations

import re
from collections.abc import Mapping

_ENUM = re.compile(r"^[A-Z][A-Z0-9_]{2,79}$")
_FIELD = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,79}$")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{4,100}$")


def safe_request_id(value: object) -> str | None:
    return value if isinstance(value, str) and _REQUEST_ID.fullmatch(value) else None


def _enum(value: object) -> str | None:
    return value if isinstance(value, str) and _ENUM.fullmatch(value) else None


def error_category(family: str, code: str) -> str:
    if family == "queryError" or code == "GOOGLE_ADS_QUERY_ERROR":
        return "query"
    if family == "authenticationError":
        return "authentication"
    if family == "authorizationError" or code in {
        "GOOGLE_ADS_ACCESS_ERROR", "CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION",
        "USER_PERMISSION_DENIED", "SERVICE_DISABLED", "API_DISABLED",
        "CUSTOMER_NOT_ENABLED", "CUSTOMER_NOT_FOUND", "DEVELOPER_TOKEN_ERROR",
    }:
        return "access"
    if family in {"quotaError", "rateLimitError"} or code == "RESOURCE_EXHAUSTED":
        return "quota"
    if family == "internalError" or code in {"UNAVAILABLE", "INTERNAL", "DEADLINE_EXCEEDED"}:
        return "transient"
    if family in {"mutateError", "fieldMaskError", "fieldError", "policyFindingError", "policyViolationError"}:
        return "validation"
    return "unknown"


def next_step_for_error(category: str, code: str) -> str:
    if code in {"SERVICE_DISABLED", "API_DISABLED"}:
        return "Enable Google Ads API in the Google Cloud project that owns this OAuth client ID."
    if code in {"CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION", "GOOGLE_ADS_ACCESS_ERROR"}:
        return "Check production access (Explorer or higher) for the OAuth client's Google Cloud project and Ads customer permissions."
    if category == "query":
        return "Fix the GAQL resource, selected fields or date filters indicated by the error. This is not an OAuth sign-in failure."
    if category == "access":
        return "Check this Google user's Ads account access and the customer/manager IDs indicated by the error."
    if category == "authentication":
        return "Check the saved Google OAuth connection and its granted Ads scope; the application session is separate."
    if category in {"quota", "transient"}:
        return "A bounded read retry may succeed after the provider recovers; never automatically replay a mutation."
    if category == "validation":
        return "Correct the indicated operation or update mask, then validate the exact changes again before approval."
    return "Use the Google request ID to inspect the upstream failure; HTTP 400 alone does not establish a permissions problem."


def _field_path(error: dict) -> str | None:
    location = error.get("location")
    elements = location.get("fieldPathElements") if isinstance(location, dict) else None
    if not isinstance(elements, list):
        return None
    parts = []
    for element in elements[:8]:
        if not isinstance(element, dict):
            continue
        name = element.get("fieldName")
        if not isinstance(name, str) or not _FIELD.fullmatch(name):
            continue
        index = element.get("index")
        if isinstance(index, int) and not isinstance(index, bool) and 0 <= index <= 999999:
            name += f"[{index}]"
        parts.append(name)
    return ".".join(parts)[:200] or None


def _error_objects(payload: object) -> list[dict]:
    envelopes = payload if isinstance(payload, list) else [payload]
    errors = []
    for envelope in envelopes:
        if not isinstance(envelope, dict):
            continue
        value = envelope.get("error")
        if isinstance(value, dict):
            errors.append(value)
        elif "error" in envelope:
            errors.append({})
        elif "details" in envelope and ("status" in envelope or "code" in envelope):
            # Direct google.rpc.Status responses from proxies/transports.
            errors.append(envelope)
    return errors


def decode_google_ads_error(payload: object, http_status: int, headers: Mapping | None = None) -> dict | None:
    """Return a safe diagnostic for either HTTP errors or embedded stream errors."""
    upstream = _error_objects(payload)
    if http_status < 400 and not upstream:
        return None
    headers = headers or {}
    request_id = safe_request_id(headers.get("request-id") or headers.get("Request-Id"))
    status = "UNKNOWN"
    errors: list[dict] = []
    reasons: list[str] = []
    messages: list[str] = []
    effective_status = http_status if http_status >= 400 else 502
    for failure in upstream:
        status = _enum(failure.get("status")) or status
        supplied_status = failure.get("code")
        if http_status < 400 and isinstance(supplied_status, int) and 400 <= supplied_status <= 599:
            effective_status = supplied_status
        if isinstance(failure.get("message"), str):
            messages.append(failure["message"][:500])
        details = failure.get("details")
        for detail in details if isinstance(details, list) else []:
            if not isinstance(detail, dict):
                continue
            request_id = request_id or safe_request_id(detail.get("requestId") or detail.get("request_id"))
            reason = _enum(detail.get("reason"))
            if reason:
                reasons.append(reason)
            nested_errors = detail.get("errors")
            for item in nested_errors if isinstance(nested_errors, list) else []:
                if not isinstance(item, dict):
                    continue
                if isinstance(item.get("message"), str):
                    messages.append(item["message"][:500])
                codes = item.get("errorCode") or item.get("error_code")
                if not isinstance(codes, dict):
                    continue
                for family, value in codes.items():
                    code = _enum(value)
                    if code and isinstance(family, str) and _FIELD.fullmatch(family):
                        errors.append({"code": code, "family": family,
                                       "category": error_category(family, code), "field": _field_path(item)})
    chosen = next((item for item in errors if item["code"] not in {"UNSPECIFIED", "UNKNOWN"}), None)
    if not chosen and reasons:
        code = reasons[0]
        chosen = {"code": code, "family": "ErrorInfo", "category": error_category("", code), "field": None}
        errors.append(chosen)
    if not chosen:
        # Conservative fallback only when Google did not supply a useful enum.
        # Provider text is never returned or logged.
        description = " ".join(messages).lower()
        code = "UNSPECIFIED"
        if "developer token" in description:
            code = "DEVELOPER_TOKEN_ERROR"
        elif any(word in description for word in ("gaql", "query", "syntax", "unrecognized field", "unknown field")):
            code = "GOOGLE_ADS_QUERY_ERROR"
        elif any(word in description for word in ("permission", "not approved", "access denied")):
            code = "GOOGLE_ADS_ACCESS_ERROR"
        chosen = {"code": code, "family": None, "category": error_category("", code), "field": None}
    if http_status < 400 and effective_status == 502:
        effective_status = {"INVALID_ARGUMENT": 400, "UNAUTHENTICATED": 401,
                            "PERMISSION_DENIED": 403, "RESOURCE_EXHAUSTED": 429,
                            "UNAVAILABLE": 503, "DEADLINE_EXCEEDED": 504}.get(status, 502)
    return {
        "origin": "google_ads_api", "http_status": effective_status,
        "api_status": status, "google_ads_error_code": chosen["code"],
        "google_ads_error_category": chosen["category"],
        "google_ads_error_family": chosen["family"],
        "google_ads_error_field": chosen["field"],
        "google_ads_errors": errors[:10], "google_request_id": request_id,
        "retryable": effective_status in {429, 500, 502, 503, 504},
        "message": "Google Ads API rejected the request. The application OAuth session may still be connected.",
        "next_step": next_step_for_error(chosen["category"], chosen["code"]),
    }
