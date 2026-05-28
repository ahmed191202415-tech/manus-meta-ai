from urllib.parse import parse_qs, urlparse


REQUIRED_UTM_KEYS = ["utm_source", "utm_medium", "utm_campaign"]
STRONG_ID_KEYS = ["ad_id", "utm_content", "campaign_id", "adset_id"]


def extract_creative_links(row: dict) -> list[dict]:
    creative = row.get("creative") or row
    links = []
    url_tags = str(creative.get("url_tags") or row.get("url_tags") or "").strip()

    for url in _walk_for_urls(creative):
        links.append(_inspect_url(url, url_tags=url_tags, meta_row=row))

    if url_tags and not links:
        links.append(_inspect_url("", url_tags=url_tags, meta_row=row))

    return links


def audit_meta_tracking_links(meta_ad_rows: list[dict], ga4_rows: list[dict] | None = None) -> dict:
    inspected = []
    for row in meta_ad_rows:
        inspected.extend(extract_creative_links(row))

    total = len(inspected)
    complete = [item for item in inspected if item["utm_complete"]]
    with_strong_ids = [item for item in inspected if item["has_strong_id"]]
    missing = {}
    for key in REQUIRED_UTM_KEYS + STRONG_ID_KEYS:
        missing[key] = sum(1 for item in inspected if key in item["missing_keys"])

    ga4_landing_pages = {str(row.get("landingPagePlusQueryString") or "").split("?")[0] for row in (ga4_rows or [])}
    matched_pages = []
    if ga4_landing_pages:
        for item in inspected:
            path = item.get("path")
            if path and path in ga4_landing_pages:
                matched_pages.append(path)

    score = 0
    if total:
        score += round((len(complete) / total) * 45)
        score += round((len(with_strong_ids) / total) * 35)
        score += 20 if matched_pages else 0

    recommendations = []
    if total == 0:
        recommendations.append("No creative landing URLs or url_tags were found.")
    if total and len(complete) < total:
        recommendations.append("Add utm_source, utm_medium, and utm_campaign to every Meta ad link.")
    if total and len(with_strong_ids) < total:
        recommendations.append("Add ad_id or campaign_id to URL tags for stronger Meta to GA4 matching.")
    if ga4_rows and not matched_pages:
        recommendations.append("Landing page paths from Meta were not found in GA4 rows; check redirects and final URLs.")

    return {
        "tracking_link_score": min(score, 100),
        "total_links": total,
        "utm_complete_links": len(complete),
        "strong_id_links": len(with_strong_ids),
        "matched_landing_pages": sorted(set(matched_pages)),
        "missing_key_counts": missing,
        "links": inspected[:100],
        "recommendations": recommendations,
    }


def _inspect_url(url: str, url_tags: str = "", meta_row: dict | None = None) -> dict:
    meta_row = meta_row or {}
    parsed = urlparse(url) if url else None
    query = {}
    if parsed:
        query.update({key: values[-1] for key, values in parse_qs(parsed.query).items() if values})
    if url_tags:
        query.update({key: values[-1] for key, values in parse_qs(url_tags).items() if values})

    missing_required = [key for key in REQUIRED_UTM_KEYS if not query.get(key)]
    missing_strong = [key for key in STRONG_ID_KEYS if not query.get(key)]
    missing_keys = missing_required + missing_strong
    return {
        "ad_id": str(meta_row.get("id") or meta_row.get("ad_id") or ""),
        "ad_name": meta_row.get("name") or meta_row.get("ad_name"),
        "campaign_id": meta_row.get("campaign_id"),
        "campaign_name": meta_row.get("campaign_name"),
        "url": url,
        "url_tags": url_tags,
        "domain": parsed.netloc if parsed else "",
        "path": parsed.path if parsed else "",
        "query": query,
        "utm_complete": not missing_required,
        "has_strong_id": any(query.get(key) for key in STRONG_ID_KEYS),
        "missing_keys": missing_keys,
    }


def _walk_for_urls(value) -> list[str]:
    urls = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"link", "url", "website_url"} and isinstance(item, str) and item.startswith(("http://", "https://")):
                urls.append(item)
            else:
                urls.extend(_walk_for_urls(item))
    elif isinstance(value, list):
        for item in value:
            urls.extend(_walk_for_urls(item))
    return list(dict.fromkeys(urls))
