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
from app.analytics.intelligence_storage import save_intelligence_run
from app.core.auth import resolve_access_token

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.post("/run")
async def analysis_run(body: AnalysisRunRequest, request: Request):
    token = await resolve_access_token(request)

    current_df = fetch_insights_df(
        body.account_id,
        token,
        body.level,
        body.fields,
        body.date_preset,
        body.since,
        body.until,
        body.filters,
        body.sort,
    )

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
        result = build_intelligence_diagnostics(daily_df, compare_df, body.level, body.top_n)
        run_id = save_intelligence_run(
            body.account_id,
            body.level,
            body.since,
            body.until,
            compare_since,
            compare_until,
            result,
        )
        return {
            "analysis_type": body.analysis_type,
            "result": result,
            "run_id": run_id,
            "compare_range": {"since": compare_since, "until": compare_until},
        }

    return {"error": "Unsupported analysis type"}