"""Shared schema for the Meta Ads intelligence pipeline.

This layer keeps computed facts, diagnostics and skipped sections explicit so
reports do not invent unavailable sections.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

CAMPAIGN_TYPES = {"sales", "messages", "leads", "awareness", "video", "traffic", "app", "unknown"}
ENTITY_LEVELS = {"account", "campaign", "adset", "ad"}


@dataclass
class AnalysisRequest:
    question: str = ""
    campaign_type: str = "unknown"
    level: str = "campaign"
    period: Optional[str] = None
    deep: bool = False
    include_breakdowns: bool = False

    def normalized_campaign_type(self) -> str:
        value = (self.campaign_type or "unknown").lower().strip()
        return value if value in CAMPAIGN_TYPES else "unknown"


@dataclass
class SkippedSection:
    section: str
    reason: str
    required_fields: List[str] = field(default_factory=list)


@dataclass
class RelationshipEdge:
    source_metric: str
    target_metric: str
    relation_type: str
    weight: float
    confidence: str
    explanation_ar: str
    evidence: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DiagnosticResult:
    code: str
    family: str
    severity: str
    confidence: str
    diagnosis_ar: str
    decision_ar: str
    evidence: Dict[str, Any] = field(default_factory=dict)
    next_metric: str = ""
    required_fields: List[str] = field(default_factory=list)


@dataclass
class PipelineResult:
    run_id: str
    phase: str
    summary_ar: str
    rows: int
    metrics: Dict[str, Any] = field(default_factory=dict)
    diagnostics: List[Dict[str, Any]] = field(default_factory=list)
    human_insights: List[Dict[str, Any]] = field(default_factory=list)
    multivariate_synthesis: List[Dict[str, Any]] = field(default_factory=list)
    relationships: List[Dict[str, Any]] = field(default_factory=list)
    skipped_sections: List[Dict[str, Any]] = field(default_factory=list)
    report_markdown: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
