from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from json import dumps
from typing import Any


def nested_value(item: dict, path: str) -> Any:
    value: Any = item
    for part in [part for part in str(path or "").split(".") if part]:
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _number(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None


def _datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _compare(actual: Any, expected: Any, operator: str) -> bool:
    if actual is None:
        return False
    actual_number, expected_number = _number(actual), _number(expected)
    if actual_number is not None and expected_number is not None:
        left, right = actual_number, expected_number
    else:
        actual_date, expected_date = _datetime(actual), _datetime(expected)
        if actual_date is not None and expected_date is not None:
            left, right = actual_date, expected_date
        elif isinstance(actual, str) and isinstance(expected, str):
            left, right = actual.casefold(), expected.casefold()
        else:
            return False
    return left >= right if operator == "gte" else left <= right


def record_matches(item: dict, filters: dict, search: str | None) -> bool:
    for key, expected in (filters or {}).items():
        actual = nested_value(item, key)
        if isinstance(expected, list):
            if actual not in expected:
                return False
        elif isinstance(expected, dict):
            if "contains" in expected and str(expected["contains"]).casefold() not in str(actual or "").casefold():
                return False
            if "gte" in expected and not _compare(actual, expected["gte"], "gte"):
                return False
            if "lte" in expected and not _compare(actual, expected["lte"], "lte"):
                return False
        elif actual != expected:
            return False
    if search:
        return str(search).casefold() in dumps(item, ensure_ascii=False, default=str).casefold()
    return True


def sort_value(value: Any) -> tuple:
    """Return a key whose elements are always mutually comparable."""
    if value is None:
        return (1, 4, "")
    number = _number(value)
    if number is not None:
        return (0, 0, number)
    date = _datetime(value)
    if date is not None:
        return (0, 1, date.timestamp())
    if isinstance(value, bool):
        return (0, 2, int(value))
    return (0, 3, str(value).casefold())
