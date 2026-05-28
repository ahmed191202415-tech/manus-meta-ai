def confidence_from_quality(tracking_quality: dict, sample_size: float) -> str:
    score = float(tracking_quality.get("score") or tracking_quality.get("tracking_score") or 0)
    if sample_size < 100:
        return "low"
    if score >= 75 and sample_size >= 500:
        return "high"
    if score >= 45:
        return "medium"
    return "low"


def severity_from_gap(value: float, high: float, medium: float) -> str:
    if value >= high:
        return "high"
    if value >= medium:
        return "medium"
    return "low"
