import re
from typing import Any

from fastapi import HTTPException

SAFE_GA4_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def validate_ga4_report_request(dimensions: list[str], metrics: list[str], limit: int | None = None) -> dict[str, Any]:
    invalid_dimensions = [item for item in dimensions if not SAFE_GA4_NAME.match(str(item or ""))]
    invalid_metrics = [item for item in metrics if not SAFE_GA4_NAME.match(str(item or ""))]
    if invalid_dimensions or invalid_metrics:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Invalid GA4 dimension or metric name.",
                "invalid_dimensions": invalid_dimensions,
                "invalid_metrics": invalid_metrics,
            },
        )
    return {
        "dimensions": dimensions,
        "metrics": metrics,
        "limit": min(max(int(limit or 100), 1), 1000),
        "validation_level": "syntax",
    }


def build_custom_report_output(raw_payload: dict, normalized_rows: list[dict], validation: dict) -> dict:
    return {
        "report_type": "ga4_custom_report",
        "property_id": raw_payload.get("property_id"),
        "date_range": raw_payload.get("date_range"),
        "schema": {
            "dimensions": validation.get("dimensions", []),
            "metrics": validation.get("metrics", []),
            "validation_level": validation.get("validation_level"),
        },
        "row_count": len(normalized_rows),
        "rows": normalized_rows,
        "raw_response": raw_payload,
    }
