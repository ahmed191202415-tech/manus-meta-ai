from fastapi import APIRouter, Request, HTTPException

from app.schemas.analysis_requests import AnalysisRunRequest
from app.analytics.preprocessing import fetch_insights_df, infer_previous_range
from app.analytics.metrics import summarize_df
from app.analytics.comparisons import build_period_comparison
from app.analytics.ranking import build_ranking
from app.analytics.funnel import build_video_funnel
from app.analytics.anomalies import build_anomaly_scan
from app.analytics.diagnostics import build_drop_reason, build_deep_root_cause
from app.analytics.prediction import build_forecast, build_prediction
from app.analytics.clustering import build_clustering
from app.analytics.decisions import (
    build_decision_score,
    build_scale_kill_hold,
    build_budget_reallocation,
)
from app.analytics.executive import build_executive_report
from app.analytics.profitability import build_break_even_analysis
from app.analytics.audit_framework import build_audit_snapshot
from app.analytics.intelligent_diagnostics import build_intelligence_diagnostics
from app.analytics.analysis_pipeline import analyze_dataframe
from app.analytics.report_builder import build_dynamic_report_ar
from app.analytics.storage_cache import cached_raw_insights, cache_coverage
from app.analytics.data_access_layer import get_analysis_dataset, strict_scope_df
from app.analytics.intelligence_storage import save_intelligence_run
from app.core.auth import resolve_access_token
from app.core.meta_client import meta_call, normalize_account_id



def _clean_json_value(value):
    import math
    try:
        import pandas as pd
        import numpy as np
        if value is pd.NA:
            return None
        if isinstance(value, pd.Timestamp):
            return value.isoformat()
        if isinstance(value, np.generic):
            value = value.item()
    except Exception:
        pass
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, dict):
        return {str(k): _clean_json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean_json_value(v) for v in value]
    if hasattr(value, 'isoformat') and not isinstance(value, (str, bytes)):
        try:
            return value.isoformat()
        except Exception:
            pass
    return value

def _num(df, col: str):
    import pandas as pd
    if col not in df.columns:
        return pd.Series([0] * len(df), index=df.index, dtype="float64")
    return pd.to_numeric(df[col], errors="coerce").fillna(0.0)


def _summarize_deep_breakdown_df(df, breakdowns):
    import pandas as pd
    if df is None or df.empty or not breakdowns:
        return {"rows": 0, "breakdowns": breakdowns, "top_segments": []}
    group_cols = [c for c in breakdowns if c in df.columns]
    if not group_cols:
        return {"rows": int(len(df)), "breakdowns": breakdowns, "top_segments": [], "note": "Meta did not return requested breakdown columns"}
    work = df.copy()
    work["_spend"] = _num(work, "spend")
    work["_impressions"] = _num(work, "impressions")
    work["_reach"] = _num(work, "reach")
    work["_clicks"] = _num(work, "inline_link_clicks") + _num(work, "link_clicks")
    work["_results"] = _num(work, "results")
    g = work.groupby(group_cols, dropna=False).agg(
        spend=("_spend", "sum"),
        impressions=("_impressions", "sum"),
        reach=("_reach", "sum"),
        clicks=("_clicks", "sum"),
        results=("_results", "sum"),
    ).reset_index()
    import numpy as np
    impressions_den = pd.to_numeric(g["impressions"], errors="coerce").replace(0, np.nan)
    results_den = pd.to_numeric(g["results"], errors="coerce").replace(0, np.nan)
    g["ctr"] = (pd.to_numeric(g["clicks"], errors="coerce") / impressions_den).replace([np.inf, -np.inf], np.nan).fillna(0)
    g["cost_per_result"] = (pd.to_numeric(g["spend"], errors="coerce") / results_den).replace([np.inf, -np.inf], np.nan).fillna(0)
    g = g.sort_values(["results", "spend"], ascending=[False, False]).head(10).fillna(0)
    return _clean_json_value({
        "rows": int(len(df)),
        "breakdowns": group_cols,
        "top_segments": g.to_dict(orient="records"),
    })


def _run_deep_breakdown_fetches(body, token: str, plans: list[dict]) -> list[dict]:
    results = []
    for plan in plans or []:
        breakdowns = plan.get("breakdowns") or []
        if not breakdowns:
            continue
        try:
            fields_value = ",".join(plan.get("fields") or []) if isinstance(plan.get("fields"), list) else (body.fields or DEEP_SAFE_FIELDS)
            try:
                df = fetch_insights_df(
                    body.account_id,
                    token,
                    plan.get("level") or body.level,
                    fields_value,
                    body.date_preset,
                    body.since,
                    body.until,
                    body.filters,
                    body.sort,
                    time_increment=str(plan.get("time_increment") or 1),
                    breakdowns=breakdowns,
                    action_breakdowns=plan.get("action_breakdowns") or ["action_type"],
                )
            except Exception:
                df = fetch_insights_df(
                    body.account_id,
                    token,
                    plan.get("level") or body.level,
                    DEEP_SAFE_FIELDS,
                    body.date_preset,
                    body.since,
                    body.until,
                    body.filters,
                    body.sort,
                    time_increment=str(plan.get("time_increment") or 1),
                    breakdowns=breakdowns,
                    action_breakdowns=plan.get("action_breakdowns") or ["action_type"],
                )
            results.append(_clean_json_value({"plan": plan, "summary": _summarize_deep_breakdown_df(df, breakdowns)}))
        except Exception as exc:
            results.append(_clean_json_value({"plan": plan, "error_type": type(exc).__name__, "message": str(exc)[:1000]}))
    return _clean_json_value(results)

def _campaign_id_from_filters(filters: str | None) -> str | None:
    if not filters:
        return None
    try:
        import json
        data = json.loads(filters)
        for item in data if isinstance(data, list) else []:
            if str(item.get("field")) in {"campaign.id", "campaign_id"}:
                val = item.get("value")
                if isinstance(val, list) and val:
                    return str(val[0])
                if val:
                    return str(val)
    except Exception:
        return None
    return None


def _strict_campaign_df(df, campaign_id: str | None):
    if not campaign_id or df is None or getattr(df, 'empty', True):
        return df
    if 'campaign_id' not in df.columns:
        return df
    return df[df['campaign_id'].astype(str) == str(campaign_id)].copy()


def _build_campaign_filter(campaign_id: str | None) -> str | None:
    if not campaign_id:
        return None
    import json
    return json.dumps([{"field": "campaign.id", "operator": "IN", "value": [str(campaign_id)]}])


def _campaign_sort_key(item: dict) -> str:
    return str(item.get("updated_time") or item.get("created_time") or item.get("start_time") or "")


def _scope_intent_from_question(question: str | None) -> str:
    q = (question or "").lower()
    account_words = ["حساب", "الحساب", "اكونت", "الأكونت", "الاكونت", "account", "ad account"]
    campaign_words = ["حملة", "الحملة", "كامبين", "campaign", "آخر كامبين", "اخر كامبين", "latest campaign"]
    ad_words = ["إعلان", "اعلان", "adset", "أدست", "ادست", "ad ", " ad"]
    has_campaign = any(w in q for w in campaign_words)
    has_account = any(w in q for w in account_words)
    has_ad = any(w in q for w in ad_words)
    if has_campaign:
        return "campaign"
    if has_account:
        return "account"
    if has_ad:
        return "ad"
    return "account"


def _question_mentions_level(question: str | None) -> bool:
    q = (question or "").lower()
    return any(w in q for w in ["adset", "أدست", "ادست", "إعلان", "اعلان", "مستوى الإعلان", "مستوى الاعلان"])


def _resolve_account_and_campaign(body: AnalysisRunRequest, token: str) -> dict:
    """Resolve scope without converting account requests into campaign requests."""
    intent = _scope_intent_from_question(body.question)
    account_id = body.account_id
    account_name = (getattr(body, 'account_name', None) or "").strip().lower()
    campaign_id = body.campaign_id or _campaign_id_from_filters(body.filters)
    campaign_name = (body.campaign_name or "").strip().lower() if body.campaign_name else ""

    if campaign_id or campaign_name:
        intent = "campaign"

    selected_account = None
    selected_campaign = None

    if account_id:
        account_id = normalize_account_id(account_id)
        selected_account = {"id": account_id}
    else:
        payload = meta_call("GET", "me/adaccounts", token, params={"fields": "id,name,account_id,account_status,currency,timezone_name", "limit": 25})
        accounts = payload.get("data") or []
        if account_name:
            matched = [a for a in accounts if account_name in str(a.get("name") or "").lower()]
            if matched:
                accounts = matched
        if not accounts:
            raise HTTPException(status_code=400, detail="No ad account could be resolved. Please authenticate Meta or provide account_id.")
        selected_account = accounts[0]
        account_id = normalize_account_id(selected_account.get("id") or selected_account.get("account_id") or "")

    if not account_id:
        raise HTTPException(status_code=400, detail="No valid ad account id could be resolved.")

    if intent == "account":
        body.account_id = account_id
        body.campaign_id = None
        body.campaign_name = None
        body.filters = None
        if not _question_mentions_level(body.question):
            body.level = "campaign"
        return {"scope": "account", "intent": intent, "account_id": account_id, "campaign_id": None, "account": selected_account, "campaign": None}

    if intent == "campaign":
        params = {"fields": "id,name,status,effective_status,objective,created_time,updated_time,start_time,stop_time", "limit": 50}
        camps = meta_call("GET", f"{account_id}/campaigns", token, params=params).get("data") or []
        best = None
        for camp in camps:
            if campaign_id and str(camp.get("id")) != str(campaign_id):
                continue
            if campaign_name and campaign_name not in str(camp.get("name") or "").lower():
                continue
            status_text = " ".join(str(camp.get(k) or "") for k in ["status", "effective_status"]).upper()
            active_bonus = "ACTIVE" in status_text
            score = ("1" if active_bonus else "0", _campaign_sort_key(camp), str(camp.get("id") or ""))
            if best is None or score > best["score"]:
                best = {"score": score, "campaign": camp}
        if best:
            selected_campaign = best["campaign"]
            campaign_id = str(selected_campaign.get("id") or campaign_id or "") or None
        if not campaign_id:
            raise HTTPException(status_code=404, detail="No campaign matched the request.")
        body.account_id = account_id
        body.campaign_id = campaign_id
        body.filters = _build_campaign_filter(campaign_id)
        return {"scope": "campaign", "intent": intent, "account_id": account_id, "campaign_id": campaign_id, "account": selected_account, "campaign": selected_campaign}

    # Ad/adset requests without a campaign stay account-scoped unless campaign_id/name is supplied.
    body.account_id = account_id
    return {"scope": "account", "intent": intent, "account_id": account_id, "campaign_id": None, "account": selected_account, "campaign": None}

DEEP_SAFE_FIELDS = "date_start,date_stop,account_id,campaign_id,campaign_name,adset_id,adset_name,ad_id,ad_name,objective,spend,impressions,reach,frequency,inline_link_clicks,outbound_clicks,actions,action_values,cost_per_action_type,cpm,cpc,ctr,quality_ranking,engagement_rate_ranking,conversion_rate_ranking"

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.post("/run")
async def analysis_run(body: AnalysisRunRequest, request: Request):
    token = await resolve_access_token(request)
    resolved_scope = _resolve_account_and_campaign(body, token)

    campaign_id_for_cache = _campaign_id_from_filters(body.filters) or body.campaign_id
    current_df, data_audit = get_analysis_dataset(
        account_id=body.account_id,
        token=token,
        level=body.level,
        fields=body.fields,
        date_preset=body.date_preset,
        since=body.since,
        until=body.until,
        filters=body.filters,
        sort=body.sort,
        campaign_id=campaign_id_for_cache,
        prefer_cache=True,
    )
    cache_meta = dict(data_audit)
    cache_meta["resolved_scope"] = resolved_scope

    compare_since = body.compare_since
    compare_until = body.compare_until

    if not (compare_since and compare_until):
        auto_since, auto_until = infer_previous_range(body.since, body.until)
        compare_since = compare_since or auto_since
        compare_until = compare_until or auto_until

    import pandas as pd
    compare_df = pd.DataFrame()

    if compare_since and compare_until:
        compare_df = fetch_insights_df(
            body.account_id,
            token,
            body.level,
            body.fields,
            None,
            compare_since,
            compare_until,
            body.filters,
            body.sort,
        )

    compare_df = strict_scope_df(compare_df, campaign_id_for_cache)

    if body.analysis_type == "summary_kpis":
        return {"analysis_type": body.analysis_type, "result": summarize_df(current_df)}

    if body.analysis_type == "period_comparison":
        return {
            "analysis_type": body.analysis_type,
            "result": build_period_comparison(current_df, compare_df),
            "compare_range": {"since": compare_since, "until": compare_until},
        }

    if body.analysis_type == "ranking":
        return {"analysis_type": body.analysis_type, "result": build_ranking(current_df, body.level, body.top_n)}

    if body.analysis_type == "video_funnel":
        return {"analysis_type": body.analysis_type, "result": build_video_funnel(current_df)}

    if body.analysis_type == "drop_reason_analysis":
        return {
            "analysis_type": body.analysis_type,
            "result": build_drop_reason(current_df, compare_df),
            "compare_range": {"since": compare_since, "until": compare_until},
        }

    if body.analysis_type == "anomaly_scan":
        daily_df = fetch_insights_df(
            body.account_id,
            token,
            body.level,
            body.fields,
            body.date_preset,
            body.since,
            body.until,
            body.filters,
            body.sort,
            time_increment="1",
        )
        return {"analysis_type": body.analysis_type, "result": build_anomaly_scan(daily_df, body.level)}

    if body.analysis_type == "executive_report":
        daily_df = fetch_insights_df(
            body.account_id,
            token,
            body.level,
            body.fields,
            body.date_preset,
            body.since,
            body.until,
            body.filters,
            body.sort,
            time_increment="1",
        )
        return {
            "analysis_type": body.analysis_type,
            "result": build_executive_report(daily_df, compare_df, body.level, body.top_n),
            "compare_range": {"since": compare_since, "until": compare_until},
        }

    if body.analysis_type == "forecast":
        daily_df = fetch_insights_df(
            body.account_id,
            token,
            body.level,
            body.fields,
            body.date_preset,
            body.since,
            body.until,
            body.filters,
            body.sort,
            time_increment="1",
        )
        return {"analysis_type": body.analysis_type, "result": build_forecast(daily_df, 7)}

    if body.analysis_type == "prediction":
        return {"analysis_type": body.analysis_type, "result": build_prediction(current_df, body.level, body.top_n)}

    if body.analysis_type == "decision_score":
        return {"analysis_type": body.analysis_type, "result": build_decision_score(current_df, body.level, body.top_n)}

    if body.analysis_type == "deep_root_cause":
        return {
            "analysis_type": body.analysis_type,
            "result": build_deep_root_cause(current_df, compare_df),
            "compare_range": {"since": compare_since, "until": compare_until},
        }

    if body.analysis_type == "scale_kill_hold_recommendation":
        return {"analysis_type": body.analysis_type, "result": build_scale_kill_hold(current_df, body.level, body.top_n)}

    if body.analysis_type == "clustering":
        return {"analysis_type": body.analysis_type, "result": build_clustering(current_df, body.level, 3)}

    if body.analysis_type == "budget_reallocation":
        return {"analysis_type": body.analysis_type, "result": build_budget_reallocation(current_df, body.level, body.top_n)}

    if body.analysis_type == "break_even_analysis":
        return {
            "analysis_type": body.analysis_type,
            "result": build_break_even_analysis(
                current_df,
                break_even_cpl=body.break_even_cpl,
                revenue_per_result=body.revenue_per_result,
                gross_margin_pct=body.gross_margin_pct,
            ),
        }

    if body.analysis_type == "audit_snapshot":
        return {
            "analysis_type": body.analysis_type,
            "result": build_audit_snapshot(current_df, compare_df, body.level),
            "compare_range": {"since": compare_since, "until": compare_until},
        }


    if body.analysis_type == "intelligence_diagnostics":
        daily_df = fetch_insights_df(
            body.account_id,
            token,
            body.level,
            body.fields,
            body.date_preset,
            body.since,
            body.until,
            body.filters,
            body.sort,
            time_increment="1",
        )
        # Feed the live Meta API data into the progressive intelligence pipeline.
        # This preserves the existing Meta pull path while adding semantic metrics,
        # SQLite raw/derived/baselines storage, relationships, skipped sections and
        # the dynamic Arabic report.
        result = analyze_dataframe(
            daily_df,
            compare_df=compare_df,
            campaign_type="unknown",
            question=body.question or "",
            level=body.level,
            db_path="exports/meta_ads_intelligence.sqlite",
        )
        deep_results = _run_deep_breakdown_fetches(body, token, result.get("deep_fetch_plans") or [])
        if deep_results:
            result["deep_breakdown_results"] = deep_results
            result["report_markdown"] = build_dynamic_report_ar(result, campaign_type=result.get("campaign_type") or "unknown", question=body.question or "")
        storage_warning = None
        legacy_run_id = None
        try:
            legacy_run_id = save_intelligence_run(
                body.account_id,
                body.level,
                body.since,
                body.until,
                compare_since,
                compare_until,
                result,
            )
        except Exception as exc:
            storage_warning = {"stage": "legacy_intelligence_storage", "error_type": type(exc).__name__, "message": str(exc)}
        return {
            "analysis_type": body.analysis_type,
            "result": result,
            "run_id": result.get("run_id"),
            "legacy_run_id": legacy_run_id,
            "storage_warning": storage_warning,
            "source": cache_meta.get("source", "meta_api_live_fetch"),
            "cache": cache_meta,
            "db_path": "exports/meta_ads_intelligence.sqlite",
            "compare_range": {"since": compare_since, "until": compare_until},
        }

    return {"error": "Unsupported analysis type"}