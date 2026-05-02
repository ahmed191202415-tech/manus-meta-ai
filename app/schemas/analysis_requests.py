from typing import Optional, Literal
from pydantic import BaseModel


class AnalysisRunRequest(BaseModel):
    account_id: str
    access_token: Optional[str] = None
    analysis_type: Literal[
        "summary_kpis",
        "period_comparison",
        "ranking",
        "video_funnel",
        "drop_reason_analysis",
        "anomaly_scan",
        "executive_report",
        "forecast",
        "prediction",
        "decision_score",
        "deep_root_cause",
        "scale_kill_hold_recommendation",
        "clustering",
        "budget_reallocation",
        "break_even_analysis",
        "audit_snapshot",
        "intelligence_diagnostics"
    ]
    level: Literal["campaign", "adset", "ad"] = "campaign"
    date_preset: Optional[str] = None
    since: Optional[str] = None
    until: Optional[str] = None
    compare_since: Optional[str] = None
    compare_until: Optional[str] = None
    filters: Optional[str] = None
    sort: Optional[str] = None
    top_n: int = 10
    fields: Optional[str] = None
    question: Optional[str] = None

    break_even_cpl: Optional[float] = None
    revenue_per_result: Optional[float] = None
    gross_margin_pct: Optional[float] = None
