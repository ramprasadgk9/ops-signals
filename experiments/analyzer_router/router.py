from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import pandas as pd
import yaml

from .analyzer_registry import AnalyzerRegistry
from .eligibility import evaluate_eligibility
from .feature_extractor import extract_series_profile
from .models import AnalyzerDecision, AnalyzerRoutingRequest, AnalyzerRoutingResult, RoutingMode


class UniversalTimeSeriesRouter:
    def __init__(
        self,
        registry: AnalyzerRegistry | None = None,
        registry_path: str | Path | None = None,
        config: dict | None = None,
        config_path: str | Path | None = None,
    ) -> None:
        self.registry = registry or AnalyzerRegistry(registry_path)
        self._explicit_config = config
        self.config_path = Path(config_path) if config_path else None
        self.config = self._load_config()

    def _load_config(self) -> dict:
        if self._explicit_config:
            return self._explicit_config
        if self.config_path and self.config_path.exists():
            loaded = yaml.safe_load(self.config_path.read_text()) or {}
            if "data_validation" in loaded:
                return loaded
        return {
            "data_validation": {
                "hard_minimum_samples": 30,
                "missing_values": {"warning_percentage": 5, "low_quality_percentage": 15, "reject_percentage": 30},
                "irregular_sampling": {"tolerance_percentage": 10, "warning_percentage": 15, "reject_percentage": 40},
                "interpolation": {"enabled": True, "maximum_gap_points": 5, "maximum_interpolated_percentage": 20},
            }
        }

    def route(self, request: AnalyzerRoutingRequest) -> AnalyzerRoutingResult:
        start = perf_counter()
        dataframe = pd.read_csv(request.csv_path)
        validation, profile, cleaned = self.profile_dataframe(dataframe, request.timestamp_column, request.value_column)

        if not validation.valid:
            return AnalyzerRoutingResult(request=request, validation=validation, profile=profile, analyzers=[], summary="Routing rejected.")

        profile.notes.extend(self._profile_notes(profile))
        decisions = []
        for capability in self.registry.analyzers():
            eligibility = evaluate_eligibility(capability, profile)
            suitability = self._suitability_score(capability, profile) if eligibility.eligible else 0.0
            final_score = round(min(1.0, eligibility.eligibility_score * suitability), 4) if eligibility.eligible else 0.0
            recommendation = self._recommendation(final_score, eligibility.eligible)
            reasons = list(eligibility.reasons)
            warnings = list(eligibility.warnings)
            if eligibility.eligible:
                reasons.extend(self._suitability_reasons(capability, profile))
                if capability.explanation_templates.get("selected"):
                    reasons.append(capability.explanation_templates["selected"])
            else:
                if capability.explanation_templates.get("excluded"):
                    warnings.append(capability.explanation_templates["excluded"])
            decisions.append(
                AnalyzerDecision(
                    analyzer=capability.analyzer,
                    display_name=capability.display_name,
                    eligible=eligibility.eligible,
                    eligibility_score=round(eligibility.eligibility_score, 4),
                    suitability_score=round(suitability, 4),
                    final_score=final_score,
                    recommendation=recommendation,
                    reasons=reasons,
                    warnings=warnings,
                    explanation=self._explain(capability, profile, eligibility.eligible, final_score),
                    parameters_tested={
                        "supported_profiles": capability.supported_profiles,
                        "eligibility_rules": capability.eligibility_rules,
                        "suitability_rules": capability.suitability_rules,
                        "scoring_rules": capability.scoring_rules,
                    },
                )
            )

        decisions = self._apply_routing_mode(decisions, request.routing_mode, request.selected_analyzers)
        export_path = self._write_result(request, profile, validation, decisions, cleaned, start)
        summary = self._summary(profile, decisions)
        return AnalyzerRoutingResult(request=request, validation=validation, profile=profile, analyzers=decisions, export_path=export_path, summary=summary)

    def profile_dataframe(self, dataframe: pd.DataFrame, timestamp_column: str | None, value_column: str | None):
        return extract_series_profile(
            dataframe,
            timestamp_column,
            value_column,
            interpolation_enabled=bool(self.config["data_validation"]["interpolation"]["enabled"]),
            maximum_gap_points=int(self.config["data_validation"]["interpolation"]["maximum_gap_points"]),
            maximum_interpolated_percentage=float(self.config["data_validation"]["interpolation"]["maximum_interpolated_percentage"]),
        )

    def _apply_routing_mode(self, decisions: list[AnalyzerDecision], mode: RoutingMode, selected: list[str]) -> list[AnalyzerDecision]:
        if mode == RoutingMode.MANUAL:
            allowed = set(selected)
            return [d for d in decisions if d.analyzer in allowed]
        if mode == RoutingMode.AUTOMATIC_WITH_OVERRIDE and selected:
            override = set(selected)
            for d in decisions:
                if d.analyzer in override and not d.eligible:
                    d.eligible = True
                    d.recommendation = "OVERRIDDEN"
                    d.reasons.append("Manually overridden by user.")
            return decisions
        return decisions

    def _suitability_score(self, capability, profile) -> float:
        rules = capability.scoring_rules or {}
        base = float(rules.get("base", 0.5) or 0.5)
        score = base
        for rule in rules.get("rules", []):
            if self._rule_matches(rule, profile):
                score += float(rule.get("add", 0.0) or 0.0)
        return float(max(0.0, min(1.0, score)))

    def _suitability_reasons(self, capability, profile) -> list[str]:
        reasons = []
        for rule in (capability.scoring_rules or {}).get("rules", []):
            if self._rule_matches(rule, profile) and rule.get("reason"):
                reasons.append(str(rule["reason"]))
        return reasons

    def _recommendation(self, final_score: float, eligible: bool) -> str:
        if not eligible:
            return "REJECTED"
        if final_score >= 0.8:
            return "RECOMMENDED"
        if final_score >= 0.55:
            return "OPTIONAL"
        return "NOT_RECOMMENDED"

    def _explain(self, capability, profile, eligible: bool, score: float) -> str:
        analyzer = capability.analyzer
        if not eligible:
            return f"{capability.display_name} was excluded because the series did not meet technical requirements."
        template = capability.explanation_templates.get("selected")
        if template:
            return f"{capability.display_name} is suitable because {template[0].lower() + template[1:] if template else template}, with score {score:.2f}."
        return f"{capability.display_name} received score {score:.2f}."

    def _rule_matches(self, rule: dict, profile) -> bool:
        metric = rule.get("metric")
        if not metric:
            return False
        value = self._profile_metric(profile, metric)
        if value is None:
            return False
        if "gte" in rule and not value >= rule["gte"]:
            return False
        if "gt" in rule and not value > rule["gt"]:
            return False
        if "lte" in rule and not value <= rule["lte"]:
            return False
        if "lt" in rule and not value < rule["lt"]:
            return False
        if "equals" in rule and not value == rule["equals"]:
            return False
        return True

    def _profile_metric(self, profile, metric: str):
        if metric == "behavior_mix":
            return int(
                sum(
                    1
                    for condition in (
                        profile.shift_index >= 0.08,
                        profile.seasonality_strength >= 0.2,
                        profile.trend_strength >= 0.12,
                    )
                    if condition
                )
            )
        return getattr(profile, metric, None)

    def recommend_analyzers_for_profile(self, profile) -> list[AnalyzerDecision]:
        decisions = []
        for capability in self.registry.analyzers():
            eligibility = evaluate_eligibility(capability, profile)
            suitability = self._suitability_score(capability, profile) if eligibility.eligible else 0.0
            final_score = round(min(1.0, eligibility.eligibility_score * suitability), 4) if eligibility.eligible else 0.0
            recommendation = self._recommendation(final_score, eligibility.eligible)
            reasons = list(eligibility.reasons)
            warnings = list(eligibility.warnings)
            if eligibility.eligible:
                reasons.extend(self._suitability_reasons(capability, profile))
                if capability.explanation_templates.get("selected"):
                    reasons.append(capability.explanation_templates["selected"])
            else:
                if capability.explanation_templates.get("excluded"):
                    warnings.append(capability.explanation_templates["excluded"])
            decisions.append(
                AnalyzerDecision(
                    analyzer=capability.analyzer,
                    display_name=capability.display_name,
                    eligible=eligibility.eligible,
                    eligibility_score=round(eligibility.eligibility_score, 4),
                    suitability_score=round(suitability, 4),
                    final_score=final_score,
                    recommendation=recommendation,
                    reasons=reasons,
                    warnings=warnings,
                    explanation=self._explain(capability, profile, eligibility.eligible, final_score),
                    parameters_tested={
                        "supported_profiles": capability.supported_profiles,
                        "eligibility_rules": capability.eligibility_rules,
                        "suitability_rules": capability.suitability_rules,
                        "scoring_rules": capability.scoring_rules,
                    },
                )
            )
        return decisions

    def _profile_notes(self, profile) -> list[str]:
        notes = []
        if profile.irregular_sampling_percentage > 15:
            notes.append("The series is irregularly sampled.")
        if profile.constant_value_percentage >= 95:
            notes.append("The series is effectively constant.")
        if profile.seasonality_strength >= 0.42:
            notes.append("Seasonal structure was detected.")
        if profile.shift_index >= 0.12:
            notes.append("Evidence of baseline shift was detected.")
        if profile.spikiness >= 0.22:
            notes.append("The signal contains noticeable spikes.")
        if profile.trend_strength >= 0.18:
            notes.append("The signal shows a meaningful trend component.")
        if profile.constant_value_percentage >= 90.0:
            notes.append("The series is nearly constant.")
        return notes

    def _summary(self, profile, decisions: list[AnalyzerDecision]) -> str:
        recommended = [d.display_name for d in decisions if d.recommendation == "RECOMMENDED"]
        optional = [d.display_name for d in decisions if d.recommendation == "OPTIONAL"]
        rejected = [d.display_name for d in decisions if d.recommendation == "REJECTED"]
        return (
            f"Profiled {profile.valid_sample_count} valid samples. "
            f"Recommended analyzers: {', '.join(recommended) if recommended else 'none'}. "
            f"Optional: {', '.join(optional) if optional else 'none'}. "
            f"Rejected: {', '.join(rejected) if rejected else 'none'}."
        )

    def _write_result(self, request: AnalyzerRoutingRequest, profile, validation, decisions: list[AnalyzerDecision], cleaned: pd.DataFrame, start: float) -> str:
        output_dir = Path("experiments/analyzer_router/output/routing_results")
        output_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "experiment_id": str(uuid4()),
            "request": asdict(request),
            "validation": asdict(validation),
            "profile": asdict(profile),
            "analyzers": [asdict(decision) for decision in decisions],
            "execution": {
                "status": "completed" if validation.valid else "rejected",
                "execution_time_seconds": round(perf_counter() - start, 4),
            },
            "cleaned_preview": cleaned.head(10).to_dict(orient="records"),
            "created_at": pd.Timestamp.utcnow().isoformat(),
        }
        path = output_dir / f"{payload['experiment_id']}.json"
        path.write_text(json.dumps(payload, indent=2, default=str))
        return str(path)
