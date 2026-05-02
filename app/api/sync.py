from __future__ import annotations
from datetime import datetime, timezone
import json
from uuid import uuid4
import uuid
from fastapi import APIRouter, Request

from app.core.auth import resolve_access_token
from app.analytics.preprocessing import fetch_insights_df
from app.analytics.semantic_metrics import expand_semantic_metrics
from app.analytics.statistical_skills_layer import add_statistical_features, build_statistical_profile
from app.analytics.analysis_storage import prepare_raw_for_storage
from app.analytics.analysis_pipeline import _derived_for_storage
from app.analytics import supabase_storage

router = APIRouter(prefix="/sync", tags=["sync"])


def _filters_for_campaign(campaign_id: str | None) -> str | None:
    if not campaign_id:
        return None
    return json.dumps([{"field":"campaign.id","operator":"IN","value":[campaign_id]}])


@router.post("/meta")
async def sync_meta_cache(payload: dict, request: Request):
    """Pull a bounded slice from Meta and persist it to Supabase.

    Intended for scheduled/background refresh. It uses the saved Meta connection.
    """
    token = await resolve_access_token(request)
    account_id = payload.get("account_id")
    if not account_id:
        return {"ok": False, "error": "account_id is required"}
    level = payload.get("level") or "ad"
    date_preset = payload.get("date_preset") or "yesterday"
    campaign_id = payload.get("campaign_id")
    question = payload.get("question") or "scheduled sync"
    filters = payload.get("filters") or _filters_for_campaign(campaign_id)
    fields = payload.get("fields")
    df = fetch_insights_df(
        account_id, token, level, fields, date_preset, payload.get("since"), payload.get("until"), filters, payload.get("sort"), time_increment=str(payload.get("time_increment") or 1)
    )
    enriched = add_statistical_features(expand_semantic_metrics(df))
    raw_storage = prepare_raw_for_storage(df, level=level, breakdown_signature="scheduled_basic")
    derived = _derived_for_storage(enriched, level=level)
    if "breakdown_signature" in derived.columns:
        derived["breakdown_signature"] = "scheduled_basic"
    profile = build_statistical_profile(enriched, level=level)
    errors=[]
    try:
        if supabase_storage.enabled():
            supabase_storage.save_dataframe_outputs(
                run_id=str(uuid.uuid4()),
                raw_df=df,
                raw_storage_df=raw_storage,
                derived_df=derived,
                baselines_df=__import__("pandas").DataFrame(),
                relationships=[],
                diagnostics=[],
                result={"sync": True, "statistical_profile": profile, "question": question},
                account_id=account_id,
                campaign_id=str(campaign_id or ""),
                level=level,
                question=question,
                campaign_type="unknown",
            )
    except Exception as exc:
        errors.append({"type": type(exc).__name__, "message": str(exc)})
    return {"ok": not errors, "source": "meta_api", "stored": True, "rows": int(len(df)), "level": level, "date_preset": date_preset, "campaign_id": campaign_id, "errors": errors, "statistical_rows": profile.get("rows"), "features_added": len(profile.get("features_added") or [])}
