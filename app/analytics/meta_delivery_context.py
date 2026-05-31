from __future__ import annotations

from collections import Counter
from typing import Any

import pandas as pd
import numpy as np

from app.core.meta_client import normalize_account_id
from app.core.pagination import meta_get_all_pages


ADSET_CONTEXT_FIELDS = (
    "id,name,campaign_id,optimization_goal,billing_event,promoted_object,"
    "destination_type,status,effective_status"
)


def fetch_adset_delivery_context(account_id: str, access_token: str, max_pages: int = 3) -> list[dict]:
    payload = meta_get_all_pages(
        f"{normalize_account_id(account_id)}/adsets",
        access_token,
        params={"fields": ADSET_CONTEXT_FIELDS, "limit": 100},
        max_pages=max_pages,
    )
    return payload.get("data", []) if isinstance(payload, dict) else []


def summarize_delivery_context(adsets: list[dict] | None, campaign_ids: set[str] | None = None, adset_ids: set[str] | None = None) -> dict:
    rows = list(adsets or [])
    if campaign_ids:
        rows = [row for row in rows if _clean(row.get("campaign_id")) in campaign_ids]
    if adset_ids:
        rows = [row for row in rows if _clean(row.get("id")) in adset_ids]

    optimization_goals = Counter(_clean(row.get("optimization_goal")) for row in rows if _clean(row.get("optimization_goal")))
    billing_events = Counter(_clean(row.get("billing_event")) for row in rows if _clean(row.get("billing_event")))
    destinations = Counter(_destination(row) for row in rows if _destination(row))
    promoted_objects = [_compact_promoted_object(row.get("promoted_object")) for row in rows if row.get("promoted_object")]

    return {
        "adsets_analyzed": len(rows),
        "optimization_goals": dict(optimization_goals.most_common()),
        "primary_optimization_goal": optimization_goals.most_common(1)[0][0] if optimization_goals else None,
        "billing_events": dict(billing_events.most_common()),
        "destinations": dict(destinations.most_common()),
        "promoted_objects": promoted_objects[:10],
        "adsets": [
            {
                "adset_id": _clean(row.get("id")),
                "adset_name": _clean(row.get("name")),
                "campaign_id": _clean(row.get("campaign_id")),
                "optimization_goal": _clean(row.get("optimization_goal")),
                "billing_event": _clean(row.get("billing_event")),
                "destination_type": _destination(row),
            }
            for row in rows[:30]
        ],
    }


def relevant_entity_ids(rows: Any) -> tuple[set[str], set[str]]:
    records = rows.to_dict(orient="records") if hasattr(rows, "to_dict") else list(rows or [])
    campaign_ids = {_clean(row.get("campaign_id")) for row in records if _clean(row.get("campaign_id"))}
    adset_ids = {_clean(row.get("adset_id")) for row in records if _clean(row.get("adset_id"))}
    return campaign_ids, adset_ids


def attach_delivery_context(df: pd.DataFrame, adsets: list[dict] | None) -> pd.DataFrame:
    if df is None or df.empty or not adsets:
        return df
    out = df.copy()
    by_adset = {_clean(row.get("id")): row for row in adsets if _clean(row.get("id"))}
    by_campaign: dict[str, list[dict]] = {}
    for row in adsets:
        by_campaign.setdefault(_clean(row.get("campaign_id")), []).append(row)

    def context_for(row: pd.Series) -> dict:
        adset = by_adset.get(_clean(row.get("adset_id")))
        if adset:
            return adset
        campaign_rows = by_campaign.get(_clean(row.get("campaign_id"))) or []
        goals = {_clean(item.get("optimization_goal")) for item in campaign_rows if _clean(item.get("optimization_goal"))}
        return campaign_rows[0] if len(goals) == 1 and campaign_rows else {}

    contexts = [context_for(row) for _, row in out.iterrows()]
    out["optimization_goal"] = [_clean(item.get("optimization_goal")) for item in contexts]
    out["billing_event"] = [_clean(item.get("billing_event")) for item in contexts]
    out["destination_type"] = [_destination(item) for item in contexts]

    from app.analytics.preprocessing import extract_best_result, extract_result_type
    actions = out["actions"].tolist() if "actions" in out.columns else [None] * len(out)
    goal_hints = [item or objective for item, objective in zip(out["optimization_goal"].tolist(), out.get("objective", pd.Series([""] * len(out))).tolist())]
    out["results"] = [extract_best_result(action, hint) for action, hint in zip(actions, goal_hints)]
    out["result_action_type"] = [extract_result_type(action, hint) for action, hint in zip(actions, goal_hints)]
    out["result_rate"] = np.where(out["impressions"] > 0, out["results"] / out["impressions"], 0.0)
    out["cpl"] = np.where(out["results"] > 0, out["spend"] / out["results"], np.nan)
    out["click_to_result_rate"] = np.where(out["inline_link_clicks"] > 0, out["results"] / out["inline_link_clicks"], 0.0)
    return out


def _destination(row: dict) -> str:
    promoted = row.get("promoted_object") if isinstance(row.get("promoted_object"), dict) else {}
    return _clean(row.get("destination_type") or promoted.get("custom_event_type") or promoted.get("object_store_url"))


def _compact_promoted_object(value: Any) -> dict:
    if not isinstance(value, dict):
        return {}
    allowed = {"custom_event_type", "pixel_id", "page_id", "application_id", "object_store_url", "product_set_id"}
    return {key: value[key] for key in allowed if value.get(key) is not None}


def _clean(value: Any) -> str:
    return str(value or "").strip()
