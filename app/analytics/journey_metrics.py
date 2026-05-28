from app.analytics.preprocessing import extract_action_value
from app.analytics.website_metrics import safe_div


def build_journey_metrics(meta_rows: list[dict], ga4_summary: dict) -> dict:
    meta_clicks = sum(float(row.get("inline_link_clicks") or row.get("clicks") or 0) for row in meta_rows)
    meta_outbound_clicks = sum(_outbound_clicks(row) for row in meta_rows)
    meta_spend = sum(float(row.get("spend") or 0) for row in meta_rows)
    impressions = sum(float(row.get("impressions") or 0) for row in meta_rows)
    ga4_sessions = float(ga4_summary.get("sessions") or 0)
    ga4_engaged_sessions = float(ga4_summary.get("engaged_sessions") or 0)
    ga4_conversions = float(ga4_summary.get("conversions") or 0)
    meta_pixel_leads = sum(extract_action_value(row.get("actions"), "lead") for row in meta_rows)
    meta_pixel_purchases = sum(extract_action_value(row.get("actions"), "purchase") for row in meta_rows)

    return {
        "meta_spend": meta_spend,
        "meta_impressions": impressions,
        "meta_clicks": meta_clicks,
        "meta_outbound_clicks": meta_outbound_clicks,
        "ga4_sessions": ga4_sessions,
        "click_to_session_rate": safe_div(ga4_sessions, meta_clicks),
        "outbound_click_to_session_rate": safe_div(ga4_sessions, meta_outbound_clicks),
        "ga4_engaged_sessions": ga4_engaged_sessions,
        "session_to_engaged_rate": safe_div(ga4_engaged_sessions, ga4_sessions),
        "ga4_conversions": ga4_conversions,
        "session_to_conversion_rate": safe_div(ga4_conversions, ga4_sessions),
        "engaged_to_conversion_rate": safe_div(ga4_conversions, ga4_engaged_sessions),
        "meta_pixel_leads": meta_pixel_leads,
        "meta_pixel_purchases": meta_pixel_purchases,
        "pixel_ga4_gap_rate": safe_div(abs((meta_pixel_leads + meta_pixel_purchases) - ga4_conversions), max(meta_pixel_leads + meta_pixel_purchases, ga4_conversions)),
    }


def _outbound_clicks(row: dict) -> float:
    value = row.get("outbound_clicks")
    if isinstance(value, list):
        return sum(float(item.get("value") or 0) for item in value if isinstance(item, dict))
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0
