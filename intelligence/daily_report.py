from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd

from intelligence.findings.schema import OperationalFinding


@dataclass(slots=True)
class OperationalIntelligenceReport:
    analysis_window_start: datetime | None
    analysis_window_end: datetime | None
    overall_health_score: float
    critical_findings: int
    significant_findings: int
    normal_findings: int
    metrics_analysed: int
    answers: dict[str, str] = field(default_factory=dict)
    top_findings: list[OperationalFinding] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["top_findings"] = [finding.to_record() for finding in self.top_findings]
        return payload


def build_daily_report(findings: list[OperationalFinding], points: pd.DataFrame) -> OperationalIntelligenceReport:
    if points.empty:
        return OperationalIntelligenceReport(
            analysis_window_start=None,
            analysis_window_end=None,
            overall_health_score=100.0,
            critical_findings=0,
            significant_findings=0,
            normal_findings=0,
            metrics_analysed=0,
            answers={
                "what_changed_yesterday": "No data available.",
                "what_should_i_investigate_first": "No findings available.",
                "did_anything_unusual_happen": "No data available.",
                "is_this_behavior_new_or_expected": "No data available.",
                "has_this_happened_before": "No data available.",
            },
            top_findings=[],
        )

    ordered = points.sort_values("timestamp")
    start_time = ordered["timestamp"].min().to_pydatetime()
    end_time = ordered["timestamp"].max().to_pydatetime()

    critical_findings = sum(1 for finding in findings if finding.health_status == "critical")
    significant_findings = sum(1 for finding in findings if finding.health_status == "significant")
    normal_findings = sum(1 for finding in findings if finding.health_status == "normal")
    top_findings = sorted(findings, key=lambda item: item.importance_score, reverse=True)
    metrics_analysed = int(ordered["metric_name"].nunique())

    top_finding = top_findings[0] if top_findings else None
    overall_health_score = _overall_health_score(findings)

    answers = {
        "what_changed_yesterday": top_finding.summary if top_finding else "No findings available.",
        "what_should_i_investigate_first": top_finding.title if top_finding else "No findings available.",
        "did_anything_unusual_happen": "Yes, significant operational change was detected." if findings else "No unusual behaviour detected.",
        "is_this_behavior_new_or_expected": _new_or_expected(top_finding),
        "has_this_happened_before": _has_this_happened_before(top_finding),
    }

    return OperationalIntelligenceReport(
        analysis_window_start=start_time,
        analysis_window_end=end_time,
        overall_health_score=overall_health_score,
        critical_findings=critical_findings,
        significant_findings=significant_findings,
        normal_findings=normal_findings,
        metrics_analysed=metrics_analysed,
        answers=answers,
        top_findings=top_findings,
    )


def _overall_health_score(findings: list[OperationalFinding]) -> float:
    if not findings:
        return 100.0
    average_importance = sum(finding.importance_score for finding in findings) / len(findings)
    return round(max(0.0, 100.0 - (average_importance * 100.0)), 2)


def _new_or_expected(top_finding: OperationalFinding | None) -> str:
    if top_finding is None:
        return "No findings available."
    if top_finding.comparison_json.get("new_behavior"):
        return "This behaviour looks new compared with the previous window."
    return "This behaviour looks broadly expected relative to the previous window."


def _has_this_happened_before(top_finding: OperationalFinding | None) -> str:
    if top_finding is None:
        return "No findings available."
    if top_finding.comparison_json.get("new_behavior"):
        return "It does not appear in the same form in the previous window."
    return "A similar pattern appears to have been present before."
