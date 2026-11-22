"""Parse Google Ads intents without silently changing report, scope or period.

This module has no credentials or network access. Structured commands are the
preferred contract; conversational reads are a compatibility layer. Writes
always require one explicit JSON command and the gateway's approval flow.
"""
from __future__ import annotations

from datetime import date as calendar_date
import json
import re

from fastapi import HTTPException


_READ_ACTIONS = {
    "ping", "status", "list_accounts", "inspect_campaign", "discover_campaign",
    "audit_crm_migration", "clone_campaign", "duplicate_campaign", "report",
    "analysis", "query", "keyword_inventory",
}
_WRITE_ACTIONS = {"prepare_mutation", "commit_mutation"}
_ADS_ACTIONS = (_READ_ACTIONS - {"status", "report", "analysis", "query"}) | _WRITE_ACTIONS
_CONFIGURATION_REPORTS = {"budgets", "conversions", "conversion_actions", "negative_keywords"}
_PROVIDERS = {"google_ads", "google ads", "google-ads", "googleads"}
_CUSTOMER = r"(?:[0-9]{3}-[0-9]{3}-[0-9]{4}|[0-9]{10})(?![0-9])"
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_ISO = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)")
_MONTHS = {
    "january": 1, "jan": 1, "يناير": 1,
    "february": 2, "feb": 2, "فبراير": 2,
    "march": 3, "mar": 3, "مارس": 3,
    "april": 4, "apr": 4, "أبريل": 4, "ابريل": 4,
    "may": 5, "مايو": 5,
    "june": 6, "jun": 6, "يونيو": 6,
    "july": 7, "jul": 7, "يوليو": 7,
    "august": 8, "aug": 8, "أغسطس": 8, "اغسطس": 8,
    "september": 9, "sep": 9, "sept": 9, "سبتمبر": 9,
    "october": 10, "oct": 10, "أكتوبر": 10, "اكتوبر": 10,
    "november": 11, "nov": 11, "نوفمبر": 11,
    "december": 12, "dec": 12, "ديسمبر": 12,
}
_MONTH_RE = "(?:" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + ")"
_PERIODS = {
    "TODAY", "YESTERDAY", "LAST_7_DAYS", "LAST_14_DAYS", "LAST_30_DAYS",
    "THIS_MONTH", "LAST_MONTH", "ALL_TIME",
}
_CAMPAIGN_NAME = re.compile(
    r"(?<![\w])(?:campaign(?:[_ ]name)?|(?:للحملة|الحملة|لحملة|حملة))[\"']?\s*[:=]?\s*[\"'«“]([^\"'»”]+)[\"'»”]",
    re.I,
)
_HYPHENATED_NAME = re.compile(r"(?<![\w])(?:[a-zA-Z][a-zA-Z0-9]*-)+[a-zA-Z0-9]+(?![\w])")


def _bad(message: str):
    raise HTTPException(422, message)


def _json_candidate(message: str):
    """Decode exactly one object while preserving the text outside its bounds."""
    start = message.find("{")
    if start < 0:
        return None, "", ""
    try:
        value, end = json.JSONDecoder().raw_decode(message[start:])
    except (json.JSONDecodeError, TypeError):
        return None, message[:start], message[start:]
    return value, message[:start], message[start + end:]


def _is_ads_object(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    provider = str(value.get("provider") or "").lower()
    if provider:
        return provider in _PROVIDERS
    return "customer_id" in value or str(value.get("action") or "").lower() in _ADS_ACTIONS


def detect_google_ads_request(command: str) -> bool:
    value = str(command or "").lower()
    parsed, _, _ = _json_candidate(str(command or ""))
    if isinstance(parsed, dict) and parsed.get("provider"):
        return str(parsed["provider"]).lower() in _PROVIDERS
    return _is_ads_object(parsed) or bool(re.search(
        r"google[_ -]?ads|google adwords|\badwords\b|googleadsservice\.(?:searchstream|search)|"
        r"\bgaql\b|\bsearch_term_view\b|جوجل\s+أ?دز|[إا]علانات\s+جوجل|"
        r"clone_campaign|duplicate_campaign|inspect_campaign|discover_campaign|"
        r"list_accounts|prepare_mutation|commit_mutation", value
    )) or ("جوجل" in value and any(word in value for word in (
        "اعلان", "إعلان", "حمل", "ads", "كلمات البحث",
    )))


def _one_labeled(message: str, label: str, value: str, name: str, excluded=()):
    matches = list(re.finditer(r"(?:" + label + r")\s*[:= -]*\s*(" + value + r")", message, re.I))
    matches = [match for match in matches if not any(a <= match.start(1) < b for a, b in excluded)]
    values = {match.group(1).replace("-", "") for match in matches}
    if len(values) > 1:
        _bad(f"Multiple {name} values were supplied. Send one explicit Google Ads command per scope.")
    return (matches[0].group(1) if matches else None), [match.span(1) for match in matches]


def _scope(message: str, body) -> dict:
    original_message = message
    message = message.translate(_DIGITS)
    manager, manager_spans = _one_labeled(
        message, r"(?<![\w])(?:manager[._ ]id|login[._ ]customer[._ ]id)",
        _CUSTOMER, "manager_id",
    )
    cid, customer_spans = _one_labeled(
        message,
        r"(?<![\w])(?:customer|account)(?:[._ ]id)?|(?:لل)?حساب(?:\s+جوجل)?(?:\s+رقم)?",
        _CUSTOMER, "customer_id", excluded=manager_spans,
    )
    campaign, campaign_spans = _one_labeled(
        message,
        r"(?<![\w])campaign(?:[._ ]id)?|(?:للحملة|الحملة|لحملة|حملة)(?:\s+رقم)?",
        r"[0-9]{1,20}(?![0-9])", "campaign_id",
    )
    group, group_spans = _one_labeled(
        message,
        r"(?<![\w])ad[._ ]group(?:[._ ]id)?|(?:للمجموعة|المجموعة)(?:\s+[إا]علانية|\s+الإعلانية)?(?:\s+رقم)?",
        r"[0-9]{1,20}(?![0-9])", "ad_group_id",
    )
    if not cid:
        cid = getattr(body, "meta_account_id", None)
    if not cid:
        excluded = manager_spans + campaign_spans + group_spans + customer_spans
        candidates = [m.group(0) for m in re.finditer(r"(?<![0-9])" + _CUSTOMER, message)
                      if not any(a <= m.start() < b for a, b in excluded)]
        if len({candidate.replace("-", "") for candidate in candidates}) > 1:
            _bad("Specify customer_id explicitly; this request contains multiple possible Google Ads account IDs.")
        cid = candidates[0] if candidates else None
    result = {"customer_id": cid}
    for name, value in (
        ("campaign_id", campaign or getattr(body, "campaign_id", None)),
        ("ad_group_id", group or getattr(body, "ad_group_id", None)),
        ("manager_id", manager or getattr(body, "manager_id", None)),
    ):
        if value is not None:
            result[name] = str(value)
    campaign_name = str(getattr(body, "campaign_name", "") or "").strip()
    name_matches = _CAMPAIGN_NAME.findall(original_message)
    if len(set(name_matches)) > 1:
        _bad("Multiple campaign names were supplied. Use one campaign_id or campaign_name.")
    if name_matches:
        campaign_name = name_matches[0]
    if not campaign_name:
        match = _HYPHENATED_NAME.search(original_message)
        if match:
            campaign_name = match.group(0)
    if campaign_name:
        result["campaign_name"] = campaign_name
    return result


def _validate_date(value: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        _bad("Use a calendar date in YYYY-MM-DD format.")
    try:
        calendar_date.fromisoformat(value)
    except ValueError:
        _bad("Invalid calendar date. Use a valid YYYY-MM-DD date.")
    return value


def _period(message: str, body, default_period: str | None = "LAST_7_DAYS") -> dict:
    """Do not turn an explicit date interval into today's/last week's report."""
    message = _CAMPAIGN_NAME.sub(" ", message)
    message = _HYPHENATED_NAME.sub(" ", message)
    message = message.translate(_DIGITS)
    dates = _ISO.findall(message)
    if not dates:
        same_month = re.search(
            r"(?<!\d)(\d{1,2})\s*(?:[-–—]|إلى|الى|to)\s*(\d{1,2})\s+(" +
            _MONTH_RE + r")\s*(\d{4})(?!\d)", message, re.I,
        )
        if same_month:
            first, last, month, year = same_month.groups()
            dates = [f"{int(year):04d}-{_MONTHS[month.lower()]:02d}-{int(day):02d}"
                     for day in (first, last)]
        else:
            named = re.findall(r"(?<!\d)(\d{1,2})\s+(" + _MONTH_RE + r")\s*(\d{4})(?!\d)", message, re.I)
            dates = [f"{int(year):04d}-{_MONTHS[month.lower()]:02d}-{int(day):02d}"
                     for day, month, year in named]
    if dates:
        if len(dates) > 2:
            _bad("Multiple reporting periods were supplied. Send one date or one start_date/end_date interval.")
        dates = [_validate_date(value) for value in dates]
        if len(dates) == 1:
            if re.search(r"\b(?:start_date|end_date)\b", message, re.I):
                _bad("Supply both start_date and end_date, or use date for a single day.")
            return {"date": dates[0]}
        if dates[0] > dates[1]:
            _bad("start_date must be on or before end_date.")
        return {"start_date": dates[0], "end_date": dates[1]}
    # A month/day expression without a year must not silently become LAST_7_DAYS.
    if re.search(r"\d\s*(?:[-–—]\s*\d{1,2}\s*)?(?:" + _MONTH_RE + r")\b", message, re.I):
        _bad("Specify the reporting year, preferably start_date/end_date in YYYY-MM-DD format.")
    start, end = getattr(body, "start_date", None), getattr(body, "end_date", None)
    if start or end:
        if not (start and end):
            _bad("Supply both start_date and end_date.")
        start, end = _validate_date(str(start)), _validate_date(str(end))
        if start > end:
            _bad("start_date must be on or before end_date.")
        return {"start_date": start, "end_date": end}
    lower = message.lower()
    named_period = re.search(r"\b(?:date_range|during)\s*[:= ]\s*([A-Za-z0-9_]+)", message, re.I)
    if named_period:
        value = named_period.group(1).upper()
        if value not in _PERIODS:
            _bad("Unsupported date_range. Use a supported preset or explicit start_date/end_date.")
        return {"date_range": value}
    periods = []
    for pattern, value in (
        (r"\btoday\b|النهارده|اليوم", "TODAY"),
        (r"\byesterday\b|امبارح|أمس", "YESTERDAY"),
        (r"\bthis month\b|هذا الشهر|الشهر الحالي", "THIS_MONTH"),
        (r"\blast month\b|الشهر الماضي|الشهر اللي فات", "LAST_MONTH"),
        (r"\ball time\b|كل الفترة|من بداية الحساب", "ALL_TIME"),
        (r"\blast\s*7(?:\s*days)?\b|آخر\s*7|اخر\s*7", "LAST_7_DAYS"),
        (r"\blast\s*14(?:\s*days)?\b|آخر\s*14|اخر\s*14", "LAST_14_DAYS"),
        (r"\blast\s*30(?:\s*days)?\b|آخر\s*30|اخر\s*30", "LAST_30_DAYS"),
    ):
        if re.search(pattern, lower):
            periods.append(value)
    if len(set(periods)) > 1:
        _bad("Multiple relative date ranges were supplied. Use one explicit reporting interval.")
    if periods:
        return {"date_range": periods[0]}
    if re.search(r"\blast\s+\d+|\b(?:last|this)\s+week\b|(?:آخر|اخر)\s*\d+|الأسبوع|الاسبوع|الشهر|الفترة\s+من|من\s+\d+\s*(?:[-–—]|إلى|الى)", lower):
        _bad("Specify start_date/end_date for this reporting period so the requested dates are preserved.")
    preset = str(getattr(body, "date_preset", "") or "").upper()
    aliases = {"LAST_7D": "LAST_7_DAYS", "LAST_14D": "LAST_14_DAYS", "LAST_30D": "LAST_30_DAYS"}
    preset = aliases.get(preset, preset)
    if preset and preset not in _PERIODS:
        _bad("Unsupported date_preset. Use explicit start_date/end_date for Google Ads.")
    return {"date_range": preset or default_period} if preset or default_period else {}


def _raw_gaql(message: str):
    """Extract a bounded query; never strip quotes from a GAQL literal."""
    for match in re.finditer(r"```(?:gaql|sql|text)?\s*\n?([\s\S]*?)```", message, re.I):
        candidate = match.group(1).strip()
        if re.match(r"SELECT\s", candidate, re.I):
            return candidate, message[:match.start()] + " " + message[match.end():]
    match = re.search(r"\bSELECT\s+.+?\bFROM\s+[a-zA-Z][a-zA-Z0-9_]*\b", message, re.I | re.S)
    if not match:
        return None, message
    candidate = message[match.start():].strip()
    # Strip string literals only from a temporary lexical view. Literal quote,
    # backslash and Unicode content in the actual query stay byte-for-byte intact.
    bare, quoted, escaped = [], None, False
    for char in candidate:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quoted:
                quoted = None
            bare.append(" ")
        elif char in "\"'":
            quoted = char
            bare.append(" ")
        else:
            bare.append(char)
    if quoted:
        _bad("GAQL contains an unmatched quote. Put the exact query in a JSON query field or a fenced gaql block.")
    view = "".join(bare)
    resource = re.search(r"\bFROM\s+([A-Za-z][A-Za-z0-9_]*)", view, re.I)
    if not resource:
        _bad("GAQL requires a FROM resource.")
    allowed = {"SELECT", "FROM", "WHERE", "AND", "OR", "IN", "NOT", "LIKE", "CONTAINS", "ANY", "ALL", "NONE",
               "BETWEEN", "DURING", "REGEXP_MATCH", "IS", "NULL", "ORDER", "BY", "ASC", "DESC", "LIMIT", "PARAMETERS",
               "TRUE", "FALSE", "include_drafts", "omit_unselected_resource_names", resource.group(1)}
    for token in re.findall(r"[\w.]+", view):
        if token.isdigit() or "." in token or token in allowed or token.upper() in allowed or re.fullmatch(r"[A-Z][A-Z0-9_]*", token):
            continue
        _bad("Text after GAQL is ambiguous. Put only the exact SELECT statement in a JSON query field or fenced gaql block.")
    if "`" in view or "{" in view or "}" in view:
        _bad("Unrecognized GAQL wrapper. Use a JSON query field or a complete fenced gaql block.")
    return candidate, message[:match.start()]


def _read_defaults(command: dict, body) -> dict:
    """Existing structured fields are defaults, never overrides or write inputs."""
    command = dict(command)
    if command.get("action") == "query":
        for key in ("campaign_id", "campaign_name", "start_date", "end_date", "date_preset"):
            value = getattr(body, key, None)
            if value not in (None, "") and command.get(key) != value:
                _bad("Put campaign and date filters in the GAQL query itself; extra query scope fields cannot be merged implicitly.")
    if command.get("action") in {"report", "analysis", "query", "keyword_inventory", "inspect_campaign", "discover_campaign"}:
        for key, body_key in (("customer_id", "meta_account_id"), ("campaign_id", "campaign_id"),
                              ("campaign_name", "campaign_name"), ("limit", "limit")):
            if command.get("action") == "query" and key in {"campaign_id", "campaign_name"}:
                continue
            value = getattr(body, body_key, None)
            if key not in command and value is not None:
                command[key] = value
        if command.get("action") in {"report", "analysis"} and not any(key in command for key in ("date", "start_date", "end_date", "date_range")):
            report = str(command.get("report") or "campaigns").strip().lower()
            command.update(_period("", body, default_period=None if report in _CONFIGURATION_REPORTS else "LAST_7_DAYS"))
    return command


def parse_google_ads_request(body) -> dict:
    message = str(getattr(body, "request", "") or "").strip()
    lower = message.lower()
    parsed, prefix, suffix = _json_candidate(message)
    has_prefix = bool(re.search(r"google[_ -]?ads\s*[:\-]?\s*(?:```(?:json)?\s*)?$", prefix, re.I))
    if isinstance(parsed, dict) and (has_prefix or _is_ads_object(parsed)):
        provider = str(parsed.get("provider") or "").lower()
        if provider and provider not in _PROVIDERS:
            _bad("The supplied provider is not Google Ads.")
        action = str(parsed.get("action") or "").lower()
        if action not in _READ_ACTIONS | _WRITE_ACTIONS:
            _bad("Specify a supported Google Ads action in the JSON command.")
        trailing = re.sub(r"^```\s*", "", suffix.strip()).strip()
        if not has_prefix:
            clean_prefix = re.sub(r"^```(?:json)?\s*", "", prefix.strip(), flags=re.I).strip()
            if clean_prefix or trailing:
                _bad("Use one Google Ads JSON object or one fenced JSON object, without an array or wrapper.")
        if action in _WRITE_ACTIONS:
            clean_prefix = re.sub(r"google[_ -]?ads\s*[:\-]?\s*", "", prefix, flags=re.I).strip()
            clean_prefix = re.sub(r"^```(?:json)?\s*", "", clean_prefix, flags=re.I).strip()
            if trailing or clean_prefix:
                _bad("Write commands must contain exactly one explicit JSON object without surrounding instructions.")
            return {**parsed, "action": action}
        return _read_defaults({**parsed, "action": action}, body)
    if re.search(r"prepare_mutation|commit_mutation|mutateOperations|approval_token|\b(?:remove|mutate|delete)\b", message, re.I):
        _bad("Google Ads writes require one explicit valid JSON command and the approval flow. No changes were made.")
    if "{" in message:
        # Preserve only the old harmless named-inspection recovery. A malformed
        # report/query must never become a different report, scope or period.
        if not re.search(r"inspect_campaign|discover_campaign", message, re.I):
            _bad("Malformed Google Ads JSON. Supply one valid JSON command; no report scope was inferred.")
        if re.search(r"[\"']action[\"']\s*:\s*[\"'](?:inspect_campaign|discover_campaign)[\"']", message, re.I) is None:
            _bad("Malformed Google Ads command.")
    query, outside_query = _raw_gaql(message)
    if query is not None:
        scope = _scope(outside_query, body)
        if not scope.get("customer_id"):
            _bad("Supply customer_id for a GAQL query; campaign IDs inside GAQL are not account IDs.")
        if any(scope.get(key) for key in ("campaign_id", "campaign_name", "ad_group_id")) or _period(outside_query, body, default_period=None):
            _bad("Put campaign, ad-group and date filters inside GAQL; extra query scope fields cannot be merged implicitly.")
        return {"action": "query", "customer_id": scope["customer_id"], "query": query, "search_stream": True,
                **({"manager_id": scope["manager_id"]} if scope.get("manager_id") else {}),
                **({"limit": body.limit} if getattr(body, "limit", None) is not None else {})}
    scope = _scope(message, body)
    explicit_inspect = bool(re.search(r"inspect_campaign|discover_campaign|inspect\s+campaign|افحص\s+(?:ال)?حملة|فحص\s+حملة", lower))
    search_terms = bool(re.search(r"search[_ ]terms?|search_term_view|عبارات\s+البحث|مصطلحات\s+البحث|كلمات\s+البحث\s+الفعلية", lower))
    performance = bool(re.search(r"\b(?:report|performance|metrics|cost|clicks|impressions|conversions|spend|daily|campaigns)\b|"
                                 r"تقرير|نتائج|أداء|اداء|نتيجة|صرف|تكلفة|نقرات|ظهور|تحويلات|يومي", lower))
    keyword = bool(re.search(r"\bkeyword(?:s|_inventory|_list)?\b|quality\s*score|(?:ال)?كلمات(?:\s+(?:المفتاحية|مفتاحية|البحث))?|جودة\s+الكلمات", lower))
    explicit_report = re.search(r"\breport\s*[:=]\s*([a-z_]+)", lower)
    if explicit_inspect:
        if not scope.get("campaign_name"):
            _bad("Specify campaign_name for inspect_campaign; use a scoped report for campaign_id.")
        return {"action": "inspect_campaign", **scope, **_period(message, body)}
    negative_keywords = bool(re.search(r"negative[_ ]keywords|الكلمات السلبية|الكلمات المستبعدة", lower))
    if keyword and not search_terms and not negative_keywords and not performance and not explicit_report:
        return {"action": "keyword_inventory",
                "customer_id": str(scope["customer_id"]).replace("-", "") if scope["customer_id"] else None,
                "campaign_id": scope.get("campaign_id"), "ad_group_id": scope.get("ad_group_id"),
                **({"manager_id": scope["manager_id"]} if scope.get("manager_id") else {})}
    if not performance and not search_terms and not explicit_report and scope.get("campaign_name"):
        return {"action": "inspect_campaign", **scope, **_period(message, body)}
    if not performance and not search_terms and any(word in lower for word in ("ربط", "connect", "حاله الاتصال", "حالة الاتصال", "status")):
        return {"action": "status"}
    if "ping" in lower:
        return {"action": "ping"}
    if re.search(r"list_accounts|list accounts|(?:عرض|اعرض) الحسابات|الحسابات الإعلانية|الحسابات الاعلانية|حساباتي", lower):
        return {"action": "list_accounts"}
    report = "campaigns"
    for pattern, kind in (
        (r"search[_ ]terms?|search_term_view|عبارات\s+البحث|مصطلحات\s+البحث|كلمات\s+البحث\s+الفعلية", "search_terms"),
        (r"negative[_ ]keywords|الكلمات السلبية|الكلمات المستبعدة", "negative_keywords"),
        (r"\bkeyword|الكلمات|كلمات البحث", "keywords"),
        (r"\bdaily\b|يومي", "daily"),
        (r"ad[_ ]groups?|مجموعات|المجموعات", "ad_groups"),
        (r"\bbudgets?\b|الميزانيات", "budgets"),
        (r"\bdevices\b|الأجهزة", "devices"),
        (r"conversion[_ ]actions?|إجراءات التحويل", "conversions"),
        (r"report\s+ads\b|تقرير الإعلانات", "ads"),
    ):
        if re.search(pattern, lower):
            report = kind
            break
    if explicit_report:
        report = explicit_report.group(1)
        if report not in {"search_terms", "negative_keywords", "keywords", "daily", "ad_groups", "budgets", "devices", "conversions", "ads", "campaigns",
                          "campaign", "ad_group", "ad_group_ad", "keyword_view", "search_term_view", "search_term", "conversion_actions"}:
            _bad("Unknown Google Ads report. Use a supported report name.")
    if not scope.get("customer_id"):
        return {"action": "list_accounts", "note": "Supply Google Ads customer_id for this report; the requested campaign is not an account ID."}
    if re.search(r"\b(?:for\s+(?:the\s+)?campaign|campaign_id)\b|للحملة|لحملة", lower) and not (scope.get("campaign_id") or scope.get("campaign_name")):
        _bad("Specify campaign_id or a quoted campaign_name so this report is not broadened to the whole account.")
    return {"action": "report", **scope, "report": report,
            **_period(message, body, default_period=None if report in _CONFIGURATION_REPORTS else "LAST_7_DAYS"),
            **({"limit": body.limit} if getattr(body, "limit", None) is not None else {})}
