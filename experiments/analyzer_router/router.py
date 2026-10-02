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


BEHAVIORAL_PROFILES = {
    "baseline_shift",
    "regime_change",
    "seasonal",
    "repeating_pattern",
    "trend",
    "spike",
    "anomaly",
    "outlier",
    "mixed",
}
PROFILE_MATCH_BONUS = 0.10
PROFILE_MISMATCH_CAP = 0.54

# Profiles split into two independent questions the feature extractor answers about a series:
# what shape does it have, and does it contain irregularities. An analyzer whose declared
# supported_profiles are entirely drawn from IRREGULARITY_PROFILES never claims anything about
# shape, so a shape-only detected_profiles (e.g. a seasonal series with no irregularity label
# yet) must not trip PROFILE_MISMATCH_CAP for it - that check is only meaningful for analyzers
# that actually claim a shape profile too (stumpy, prophet, ruptures, kats, ...).
#
# The profile label alone isn't reliable evidence of this, though: adtk's supported_profiles
# filters down to {spike, outlier} (its "seasonal_anomaly" entry doesn't match the fixed
# vocabulary's "seasonal"), but its own scoring_rules reward seasonality_strength directly - it's
# a seasonal-contradiction detector that genuinely needs shape, mislabeled by a naming gap. So
# irregularity-only status also requires the analyzer's own scoring rules to never test a shape
# metric - letting its own declared evidence, not just its profile label, decide. See
# docs/analyzer-recommendation.md, "Shape vs. irregularity profile matching".
IRREGULARITY_PROFILES = {"anomaly", "outlier", "spike", "baseline_shift", "regime_change"}
SHAPE_METRICS = {
    "seasonality_strength",
    "seasonality_peak_strength",
    "seasonality_dominant_lag",
    "trend_strength",
    "trend_slope",
    "trend_fit_r2",
}


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
        decisions = [self._build_decision(capability, profile) for capability in self.registry.analyzers()]

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
        profile_match, _ = self._profile_match(capability, profile)
        behavioral_supported = self._behavioral_supported_profiles(capability)
        irregularity_only = self._is_irregularity_only(capability)
        if profile_match and behavioral_supported:
            score += PROFILE_MATCH_BONUS
        elif behavioral_supported and not irregularity_only:
            score = min(score, PROFILE_MISMATCH_CAP)
        return float(max(0.0, min(1.0, score)))

    def _suitability_reasons(self, capability, profile) -> list[str]:
        reasons = []
        for rule in (capability.scoring_rules or {}).get("rules", []):
            if self._rule_matches(rule, profile) and rule.get("reason"):
                reasons.append(str(rule["reason"]))
        return reasons

    def _matched_scoring_rules(self, capability, profile) -> list[dict]:
        matches = []
        for rule in (capability.scoring_rules or {}).get("rules", []):
            if self._rule_matches(rule, profile):
                matches.append(dict(rule))
        return matches

    def _profile_match(self, capability, profile) -> tuple[bool, set[str]]:
        behavioral_supported = self._behavioral_supported_profiles(capability)
        if not behavioral_supported:
            return True, set()
        detected = {
            str(item).strip().lower()
            for item in getattr(profile, "detected_profiles", [])
            if str(item).strip().lower() in BEHAVIORAL_PROFILES
        }
        matched = behavioral_supported.intersection(detected)
        return bool(matched), matched

    @staticmethod
    def _rules_reference_shape_metrics(capability) -> bool:
        rules = (capability.scoring_rules or {}).get("rules", [])
        return any(rule.get("metric") in SHAPE_METRICS for rule in rules)

    def _is_irregularity_only(self, capability) -> bool:
        behavioral_supported = self._behavioral_supported_profiles(capability)
        return (
            bool(behavioral_supported)
            and behavioral_supported <= IRREGULARITY_PROFILES
            and not self._rules_reference_shape_metrics(capability)
        )

    def _behavioral_supported_profiles(self, capability) -> set[str]:
        return {
            str(item).strip().lower()
            for item in getattr(capability, "supported_profiles", [])
            if str(item).strip().lower() in BEHAVIORAL_PROFILES
        }

    def _profile_match_reason(self, capability, profile) -> str:
        profile_match, matched_profiles = self._profile_match(capability, profile)
        behavioral_supported = self._behavioral_supported_profiles(capability)
        detected = sorted(
            {
                str(item).strip().lower()
                for item in getattr(profile, "detected_profiles", [])
                if str(item).strip().lower() in BEHAVIORAL_PROFILES
            }
        )
        if not behavioral_supported:
            return "No behavioral profile restriction is configured for this analyzer."
        if profile_match:
            return f"Matched detected profiles: {', '.join(sorted(matched_profiles))}."
        if self._is_irregularity_only(capability):
            detected_text = ", ".join(detected) if detected else "none"
            return (
                f"This analyzer only claims irregularity profiles ({', '.join(sorted(behavioral_supported))}), "
                f"not shape - the series' shape profile ({detected_text}) is not held against it; its own "
                "scoring rules decide the score."
            )
        detected_text = ", ".join(detected) if detected else "none"
        return f"No supported behavioral profile matched the detected profiles: {detected_text}."

    def _recommendation(self, final_score: float, eligible: bool) -> str:
        if not eligible:
            return "REJECTED"
        if final_score >= 0.8:
            return "RECOMMENDED"
        if final_score >= 0.55:
            return "OPTIONAL"
        return "NOT_RECOMMENDED"

    def _explain(self, capability, profile, eligible: bool, score: float, eligibility_reasons: list[str] | None = None) -> str:
        if not eligible:
            reason = eligibility_reasons[0] if eligibility_reasons else "the series did not meet technical requirements"
            return f"{capability.display_name} was excluded because {reason[0].lower() + reason[1:] if reason else reason}"
        profile_match, matched_profiles = self._profile_match(capability, profile)
        behavioral_supported = self._behavioral_supported_profiles(capability)
        if profile_match and matched_profiles:
            return (
                f"{capability.display_name} matched the detected {self._format_profile_list(sorted(matched_profiles))} profiles, "
                f"with final score {score:.2f}."
            )
        if behavioral_supported and self._is_irregularity_only(capability):
            return (
                f"{capability.display_name} only claims irregularity profiles, not shape, so the series' shape is "
                f"not held against it here. Final score {score:.2f}, from its own irregularity evidence."
            )
        if behavioral_supported:
            return (
                f"{capability.display_name} is technically eligible, but its supported behavioral profiles did not "
                f"match the detected series behavior. Final score {score:.2f}."
            )
        return f"{capability.display_name} received score {score:.2f}."

    def _routing_reason(self, capability, profile, eligible: bool, score: float, eligibility_reasons: list[str] | None = None) -> str:
        if not eligible:
            reason = eligibility_reasons[0] if eligibility_reasons else "technical eligibility checks failed"
            return f"{capability.display_name} was rejected because {reason[0].lower() + reason[1:] if reason else reason}"
        return self._explain(capability, profile, eligible, score, eligibility_reasons)

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
        if metric == "shift_index":
            detected = {str(item).strip().lower() for item in getattr(profile, "detected_profiles", [])}
            if "baseline_shift" not in detected and "regime_change" not in detected:
                return 0.0
            return getattr(profile, metric, None)
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
        return [self._build_decision(capability, profile) for capability in self.registry.analyzers()]

    def _build_decision(self, capability, profile) -> AnalyzerDecision:
        eligibility = evaluate_eligibility(capability, profile)
        suitability = self._suitability_score(capability, profile) if eligibility.eligible else 0.0
        final_score = round(min(1.0, eligibility.eligibility_score * suitability), 4) if eligibility.eligible else 0.0
        recommendation = self._recommendation(final_score, eligibility.eligible)
        profile_match, matched_profiles = self._profile_match(capability, profile)
        behavioral_supported = self._behavioral_supported_profiles(capability)
        reasons = list(eligibility.reasons)
        warnings = list(eligibility.warnings)
        if eligibility.eligible:
            profile_reason = self._profile_match_reason(capability, profile)
            reasons.append(profile_reason)
            reasons.extend(self._suitability_reasons(capability, profile))
            if capability.explanation_templates.get("selected"):
                reasons.append(capability.explanation_templates["selected"])
        else:
            if capability.explanation_templates.get("excluded"):
                warnings.append(capability.explanation_templates["excluded"])
        routing_reason = self._routing_reason(capability, profile, eligibility.eligible, final_score, eligibility.reasons)
        return AnalyzerDecision(
            analyzer=capability.analyzer,
            display_name=capability.display_name,
            eligible=eligibility.eligible,
            eligibility_score=round(eligibility.eligibility_score, 4),
            suitability_score=round(suitability, 4),
            final_score=final_score,
            recommendation=recommendation,
            reasons=reasons,
            warnings=warnings,
            explanation=self._explain(capability, profile, eligibility.eligible, final_score, eligibility.reasons),
            routing_reason=routing_reason,
            matched_profiles=sorted(matched_profiles),
            parameters_tested={
                "supported_profiles": capability.supported_profiles,
                "eligibility_rules": capability.eligibility_rules,
                "suitability_rules": capability.suitability_rules,
                "scoring_rules": capability.scoring_rules,
                "detected_profiles": list(getattr(profile, "detected_profiles", [])),
                "matched_profiles": sorted(matched_profiles),
                "profile_match": profile_match,
                "behavioral_supported_profiles": sorted(behavioral_supported),
                "matched_scoring_rules": self._matched_scoring_rules(capability, profile),
                "suitability_explanation": routing_reason,
            },
        )

    @staticmethod
    def _format_profile_list(profiles: list[str]) -> str:
        if len(profiles) <= 1:
            return profiles[0] if profiles else "none"
        if len(profiles) == 2:
            return f"{profiles[0]} and {profiles[1]}"
        return f"{', '.join(profiles[:-1])}, and {profiles[-1]}"

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
