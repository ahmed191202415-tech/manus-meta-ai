from urllib.parse import urlparse


def build_clarity_ad_behavior(matched_entities: dict, link_audit: dict, clarity_rows: list[dict], limit: int = 20) -> list[dict]:
    links_by_ad = {}
    for item in link_audit.get("links") or []:
        ad_id = str(item.get("ad_id") or "").strip()
        if ad_id:
            links_by_ad.setdefault(ad_id, []).append(item)

    results = []
    for ad in (matched_entities.get("ads") or [])[:limit]:
        ad_id = str(ad.get("ad_id") or "").strip()
        campaign_values = {
            _clean(ad.get("campaign_id")),
            _clean(ad.get("campaign_name")),
        } - {""}
        paths = {_clean_path(link.get("url") or link.get("path")) for link in links_by_ad.get(ad_id, [])}
        paths.discard("")

        rows = []
        for row in clarity_rows:
            clarity_campaign = _clean(row.get("Campaign"))
            clarity_url_path = _clean_path(row.get("URL") or row.get("Url"))
            if campaign_values and clarity_campaign in campaign_values:
                rows.append(row)
            elif paths and clarity_url_path in paths:
                rows.append(row)

        results.append({
            "campaign_id": ad.get("campaign_id"),
            "campaign_name": ad.get("campaign_name"),
            "adset_id": ad.get("adset_id"),
            "adset_name": ad.get("adset_name"),
            "ad_id": ad_id,
            "ad_name": ad.get("ad_name"),
            "ga4_metrics": ad.get("ga4_metrics", {}),
            "clarity_matched_rows": len(rows),
            "clarity_behavior": _summarize_rows(rows),
            "matching_basis": _matching_basis(campaign_values, paths, rows),
        })
    return results


def _summarize_rows(rows: list[dict]) -> dict:
    sessions = sum(_num(row.get("totalSessionCount") or row.get("sessionsCount")) for row in rows)
    frustration = sum(_num(row.get("subTotal")) for row in rows if row.get("metricName") in {"DeadClickCount", "RageClickCount", "ErrorClickCount", "QuickbackClick"})
    return {
        "sessions": sessions,
        "frustration_events": frustration,
        "frustration_rate": frustration / sessions if sessions else 0.0,
        "top_urls": _top_values(rows, "URL"),
        "devices": _top_values(rows, "Device"),
        "campaigns": _top_values(rows, "Campaign"),
    }


def _matching_basis(campaign_values: set[str], paths: set[str], rows: list[dict]) -> list[str]:
    basis = []
    row_campaigns = {_clean(row.get("Campaign")) for row in rows}
    row_paths = {_clean_path(row.get("URL") or row.get("Url")) for row in rows}
    if campaign_values and campaign_values.intersection(row_campaigns):
        basis.append("clarity_campaign")
    if paths and paths.intersection(row_paths):
        basis.append("landing_page_url")
    return basis


def _top_values(rows: list[dict], key: str) -> list[dict]:
    totals = {}
    for row in rows:
        value = _clean(row.get(key))
        if not value:
            continue
        totals[value] = totals.get(value, 0.0) + _num(row.get("totalSessionCount") or row.get("sessionsCount"))
    return [{"value": key, "sessions": value} for key, value in sorted(totals.items(), key=lambda item: item[1], reverse=True)[:5]]


def _clean(value) -> str:
    return str(value or "").strip()


def _clean_path(value) -> str:
    text = _clean(value)
    if not text:
        return ""
    if text.startswith(("http://", "https://")):
        return urlparse(text).path or "/"
    return text.split("?")[0]


def _num(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0
