from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.analytics.analysis_pipeline import analyze_dataframe, infer_campaign_type_from_metrics
from app.analytics.preprocessing import DEFAULT_INSIGHTS_FIELDS, fetch_insights_df, infer_previous_range
from app.core.auth import resolve_access_token
from app.core.meta_client import meta_call, normalize_account_id

router = APIRouter(prefix="/analysis", tags=["campaign_analysis"])


class CampaignAnalysisRequest(BaseModel):
    account_id: str
    campaign_id: str
    since: Optional[str] = None
    until: Optional[str] = None
    date_preset: Optional[str] = None
    compare_since: Optional[str] = None
    compare_until: Optional[str] = None
    level: str = "ad"
    question: str = "حلل هذه الحملة"
    fields: Optional[str] = None
    deep: bool = False


def _campaign_type_from_objective(objective: str) -> str:
    obj = (objective or "").lower()
    if any(x in obj for x in ["sales", "conversion", "purchase", "catalog"]):
        return "sales"
    if "lead" in obj:
        return "leads"
    if any(x in obj for x in ["message", "messenger", "whatsapp"]):
        return "messages"
    if "video" in obj:
        return "video"
    if any(x in obj for x in ["awareness", "reach", "brand"]):
        return "awareness"
    if "traffic" in obj:
        return "traffic"
    if "app" in obj:
        return "app"
    return "unknown"


def _campaign_filter(campaign_id: str) -> str:
    return '[{"field":"campaign.id","operator":"IN","value":["' + str(campaign_id) + '"]}]'


@router.post("/campaign")
async def analyze_campaign(body: CampaignAnalysisRequest, token: str = Depends(resolve_access_token)):
    """Analyze one campaign from live Meta API data.

    User path: choose/request a campaign -> pull metadata -> pull daily insights ->
    infer campaign type -> run progressive pipeline -> store/report.
    """
    if not body.date_preset and not (body.since and body.until):
        raise HTTPException(status_code=400, detail="Provide since/until or date_preset.")

    account_id = normalize_account_id(body.account_id)
    campaign = meta_call(
        "GET",
        str(body.campaign_id),
        token,
        params={"fields": "id,name,status,effective_status,objective,buying_type,daily_budget,lifetime_budget,start_time,stop_time,created_time,updated_time"},
    )
    objective_type = _campaign_type_from_objective(campaign.get("objective", ""))
    filters = _campaign_filter(body.campaign_id)

    current_df = fetch_insights_df(
        account_id,
        token,
        body.level,
        body.fields or DEFAULT_INSIGHTS_FIELDS,
        body.date_preset,
        body.since,
        body.until,
        filters,
        sort=None,
        time_increment="1",
    )

    compare_since = body.compare_since
    compare_until = body.compare_until
    if not (compare_since and compare_until):
        auto_since, auto_until = infer_previous_range(body.since, body.until)
        compare_since = compare_since or auto_since
        compare_until = compare_until or auto_until

    compare_df = None
    if compare_since and compare_until:
        compare_df = fetch_insights_df(
            account_id,
            token,
            body.level,
            body.fields or DEFAULT_INSIGHTS_FIELDS,
            None,
            compare_since,
            compare_until,
            filters,
            sort=None,
            time_increment="1",
        )

    # If objective mapping is inconclusive, infer from actual events.
    inferred_from_events = infer_campaign_type_from_metrics(current_df, objective_type)
    result = analyze_dataframe(
        current_df,
        compare_df=compare_df,
        campaign_type=inferred_from_events,
        question=body.question,
        level=body.level,
        db_path="exports/meta_ads_intelligence.sqlite",
    )

    return {
        "analysis_type": "campaign_intelligence",
        "source": "meta_api_live_campaign_fetch",
        "campaign": campaign,
        "campaign_type": inferred_from_events,
        "objective_type": objective_type,
        "account_id": account_id,
        "level": body.level,
        "date_range": {"since": body.since, "until": body.until, "date_preset": body.date_preset},
        "compare_range": {"since": compare_since, "until": compare_until},
        "result": result,
        "run_id": result.get("run_id"),
        "db_path": "exports/meta_ads_intelligence.sqlite",
    }
