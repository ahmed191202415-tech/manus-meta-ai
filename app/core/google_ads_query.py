"""Bound explicit GAQL reads without altering literal values or dropping scope."""
from __future__ import annotations

import re

from fastapi import HTTPException

MAX_QUERY_ROWS = 300
_ALLOWED = {
    "action", "provider", "customer_id", "manager_id", "login_customer_id",
    "query", "search_stream", "limit",
}


def _bad(message: str):
    raise HTTPException(422, message)


def _lexical_view(query: str) -> str:
    """Blank quoted values, preserving offsets for top-level clause edits."""
    output, quote, escaped = [], None, False
    for char in query:
        if quote:
            output.append(" ")
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in "'\"":
            quote = char
            output.append(" ")
        else:
            output.append(char)
    if quote:
        _bad("GAQL has an unterminated string literal.")
    return "".join(output)


def prepare_query(command: dict) -> dict:
    unexpected = [key for key, value in command.items()
                  if key not in _ALLOWED and value not in (None, "", [], {})]
    if unexpected:
        _bad("Query commands cannot silently apply extra filters (" + ", ".join(sorted(unexpected)) +
             "). Put every campaign, date and report filter in the GAQL query or use action=report.")
    query = command.get("query")
    if not isinstance(query, str):
        _bad("query must be a GAQL SELECT string.")
    query = query.strip()
    if len(query) > 6000 or not re.match(r"(?is)^SELECT\s+", query):
        _bad("Only one read-only GAQL SELECT statement of at most 6000 characters is supported.")
    view = _lexical_view(query)
    if any(marker in view for marker in (";", "--", "/*", "*/")) or len(re.findall(r"\bSELECT\b", view, re.I)) != 1:
        _bad("Only one read-only GAQL SELECT statement without comments is supported.")
    if not re.search(r"\bFROM\s+[a-z][a-z0-9_]*\b", view, re.I):
        _bad("GAQL requires a FROM resource.")
    raw_limit = command.get("limit", 100)
    if isinstance(raw_limit, bool) or not isinstance(raw_limit, (int, str)) or not re.fullmatch(r"[0-9]+", str(raw_limit)) or int(raw_limit) < 1:
        _bad("limit must be a positive integer.")
    display_limit = min(int(raw_limit), MAX_QUERY_ROWS)
    stream = command.get("search_stream", False)
    if not isinstance(stream, bool):
        _bad("search_stream must be true or false.")
    matches = list(re.finditer(r"\bLIMIT\b", view, re.I))
    if len(matches) > 1:
        _bad("GAQL may contain only one LIMIT clause.")
    source_limit = None
    read_limit = display_limit + 1
    if matches:
        at = matches[0].start()
        match = re.match(r"(?i)LIMIT\s+([0-9]+)(?=\s|$)", view[at:])
        if not match or int(match.group(1)) < 1:
            _bad("GAQL LIMIT must be a positive integer.")
        source_limit = int(match.group(1))
        after = at + match.end()
        remainder = view[after:].strip()
        if remainder and not re.match(r"(?i)^PARAMETERS\b", remainder):
            _bad("GAQL LIMIT must precede PARAMETERS or end the query.")
        read_limit = min(read_limit, source_limit)
        # Never widen the user's own LIMIT. Fetch at most one sentinel row.
        query = query[:at] + f"LIMIT {read_limit}" + query[after:]
    else:
        parameters = re.search(r"\bPARAMETERS\b", view, re.I)
        at = parameters.start() if parameters else len(query)
        query = query[:at].rstrip() + f" LIMIT {read_limit}" + (" " + query[at:] if parameters else "")
    return {
        "query": query, "requested_query": command["query"].strip(),
        "display_limit": display_limit, "read_limit": read_limit,
        "query_row_limit": source_limit, "search_stream": stream,
    }


def finalize_query(plan: dict, result: dict) -> dict:
    rows = result["rows"]
    truncated = bool(result.get("truncated")) or len(rows) > plan["display_limit"]
    visible = rows[:plan["display_limit"]]
    # A caller-supplied LIMIT can hide more rows even when transport has no
    # further page. Do not label that result as an entire account/period total.
    limited_by_query = plan["query_row_limit"] is not None and len(rows) >= plan["query_row_limit"]
    return {
        **result, "rows": visible, "count": len(visible), "truncated": truncated,
        "query_limited": limited_by_query, "partial": truncated or limited_by_query,
        "gaql": plan["query"], "requested_gaql": plan["requested_query"],
        "scope": "explicit_gaql", "summary_scope": "returned_rows",
    }
