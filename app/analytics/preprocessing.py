import pandas as pd
import numpy as np
from typing import Any, List, Dict, Optional

from app.config import ANALYSIS_DEFAULT_DATE_PRESET, ANALYSIS_MAX_PAGES, ANALYSIS_PAGE_LIMIT
from app.analytics.goal_context import LEAD_ACTIONS, MESSAGE_ACTIONS, PURCHASE_ACTIONS
from app.core.meta_client import normalize_account_id
from app.core.pagination import meta_get_all_pages


DEFAULT_INSIGHTS_FIELDS = (
    "account_id,account_name,campaign_id,campaign_name,adset_id,adset_name,ad_id,ad_name,"
    "objective,spend,reach,frequency,impressions,inline_link_clicks,ctr,cpc,cpm,"
    "actions,action_values,cost_per_action_type,video_play_actions,"
    "video_p25_watched_actions,video_p50_watched_actions,video_p75_watched_actions,"
    "video_p95_watched_actions,video_p100_watched_actions,video_avg_time_watched_actions,"
    "video_thruplay_watched_actions,outbound_clicks,outbound_clicks_ctr,website_ctr,"
    "purchase_roas,date_start,date_stop"
)


def extract_action_value(actions: Any, action_type: str) -> float:
    if not isinstance(actions, list):
        return 0.0
    for item in actions:
        if item.get("action_type") == action_type:
            try:
                return float(item.get("value", 0))
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def extract_video_action(actions: Any) -> float:
    if not isinstance(actions, list) or not actions:
        return 0.0
    try:
        return float(actions[0].get("value", 0))
    except (TypeError, ValueError, AttributeError, IndexError):
        return 0.0


def _objective_result_actions(objective: Any) -> list[str]:
    value = str(objective or "").lower()
    if "message" in value or "whatsapp" in value or "conversation" in value:
        return list(MESSAGE_ACTIONS)
    if "lead" in value:
        return list(LEAD_ACTIONS)
    if "sales" in value or "conversion" in value or "purchase" in value or "catalog" in value:
        return list(PURCHASE_ACTIONS)
    return []


def extract_best_result(actions: Any, objective: Any = None) -> float:
    # Meta reports different "result" action types depending on campaign objective.
    objective_actions = _objective_result_actions(objective)
    if objective_actions:
        objective_value = max((extract_action_value(actions, action_type) for action_type in objective_actions), default=0.0)
        if objective_value > 0:
            return objective_value

    result_action_types = [
        "offsite_complete_registration_add_meta_leads",
        "onsite_conversion.lead_grouped",
        "lead",
        "purchase",
        "omni_purchase",
        "offsite_conversion.fb_pixel_purchase",
        "onsite_conversion.purchase",
        "messaging_conversation_started_7d",
        "onsite_conversion.messaging_conversation_started_7d",
        "onsite_conversion.messaging_first_reply",
        "contact",
        "submit_application",
        "complete_registration",
    ]
    return max((extract_action_value(actions, action_type) for action_type in result_action_types), default=0.0)


def extract_result_type(actions: Any, objective: Any = None) -> str:
    objective_actions = _objective_result_actions(objective)
    candidate_actions = objective_actions or [
        "offsite_complete_registration_add_meta_leads",
        "onsite_conversion.lead_grouped",
        "lead",
        "purchase",
        "omni_purchase",
        "offsite_conversion.fb_pixel_purchase",
        "onsite_conversion.purchase",
        "messaging_conversation_started_7d",
        "onsite_conversion.messaging_conversation_started_7d",
        "onsite_conversion.messaging_first_reply",
        "contact",
        "submit_application",
        "complete_registration",
    ]
    values = [(action_type, extract_action_value(actions, action_type)) for action_type in candidate_actions]
    values = [item for item in values if item[1] > 0]
    if not values:
        return ""
    return max(values, key=lambda item: item[1])[0]


def safe_div(a: float, b: float) -> float:
    return float(a) / float(b) if b not in (0, 0.0, None) else 0.0


def frame_from_insights(rows: List[Dict[str, Any]], level: str) -> pd.DataFrame:
    df = pd.DataFrame(rows or [])
    if df.empty:
        return df

    numeric_cols = ["spend", "reach", "frequency", "impressions", "inline_link_clicks", "ctr", "cpc", "cpm"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    actions_series = df.get("actions", pd.Series(dtype=object))
    objective_series = df.get("objective", pd.Series([""] * len(df)))
    df["results"] = [extract_best_result(actions, objective) for actions, objective in zip(actions_series, objective_series)]
    df["result_action_type"] = [extract_result_type(actions, objective) for actions, objective in zip(actions_series, objective_series)]

    df["video_p50"] = df.get("video_p50_watched_actions", pd.Series(dtype=object)).apply(extract_video_action)
    df["video_p75"] = df.get("video_p75_watched_actions", pd.Series(dtype=object)).apply(extract_video_action)
    df["video_p95"] = df.get("video_p95_watched_actions", pd.Series(dtype=object)).apply(extract_video_action) if "video_p95_watched_actions" in df.columns else 0.0
    df["video_p100"] = df.get("video_p100_watched_actions", pd.Series(dtype=object)).apply(extract_video_action) if "video_p100_watched_actions" in df.columns else 0.0

    df["result_rate"] = np.where(df["impressions"] > 0, df["results"] / df["impressions"], 0.0)
    df["p50_rate"] = np.where(df["impressions"] > 0, df["video_p50"] / df["impressions"], 0.0)
    df["p75_rate"] = np.where(df["impressions"] > 0, df["video_p75"] / df["impressions"], 0.0)
    df["cpl"] = np.where(df["results"] > 0, df["spend"] / df["results"], np.nan)
    df["click_to_result_rate"] = np.where(df["inline_link_clicks"] > 0, df["results"] / df["inline_link_clicks"], 0.0)

    name_col = f"{level}_name"
    id_col = f"{level}_id"
    if name_col not in df.columns:
        df[name_col] = "Unknown"
    if id_col not in df.columns:
        df[id_col] = "Unknown"

    if "date_start" in df.columns:
        df["date_start"] = pd.to_datetime(df["date_start"], errors="coerce")

    return df


def infer_previous_range(since: Optional[str], until: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    if not since or not until:
        return None, None
    try:
        since_dt = pd.to_datetime(since)
        until_dt = pd.to_datetime(until)
    except Exception:
        return None, None

    if pd.isna(since_dt) or pd.isna(until_dt) or since_dt > until_dt:
        return None, None

    delta_days = (until_dt - since_dt).days + 1
    prev_until = since_dt - pd.Timedelta(days=1)
    prev_since = prev_until - pd.Timedelta(days=delta_days - 1)
    return prev_since.strftime("%Y-%m-%d"), prev_until.strftime("%Y-%m-%d")


def fetch_insights_df(
    account_id: str,
    access_token: str,
    level: str,
    fields: Optional[str],
    date_preset: Optional[str],
    since: Optional[str],
    until: Optional[str],
    filters: Optional[str],
    sort: Optional[str],
    time_increment: Optional[str] = None,
) -> pd.DataFrame:
    account_id = normalize_account_id(account_id)

    params: Dict[str, Any] = {
        "level": level,
        "fields": fields or DEFAULT_INSIGHTS_FIELDS,
        "limit": ANALYSIS_PAGE_LIMIT,
    }

    if not date_preset and not (since and until):
        date_preset = ANALYSIS_DEFAULT_DATE_PRESET

    if date_preset:
        params["date_preset"] = date_preset

    if since and until:
        params["time_range"] = {"since": since, "until": until}
        params.pop("date_preset", None)

    if filters:
        params["filtering"] = filters
    if sort:
        params["sort"] = sort
    if time_increment:
        params["time_increment"] = time_increment

    payload = meta_get_all_pages(f"{account_id}/insights", access_token, params=params, max_pages=ANALYSIS_MAX_PAGES)
    return frame_from_insights(payload.get("data", []), level)
