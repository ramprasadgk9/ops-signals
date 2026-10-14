from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from intelligence.analyzer_registry import (
    AnalyzerRegistration,
    AnalyzerRegistrationError,
    instantiate,
    library_installed,
    load_registrations,
)
from intelligence.analyzers.base import Analyzer
from intelligence.config import AnalyzerConfig, AppConfig

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[1]


# The router's behavioral profiles, grouped the way the feature extractor detects them (one group
# per independent question it answers about a series). "mixed" only says several groups are active.
PROFILE_GROUPS = {
    "spike": {"anomaly", "outlier", "spike"},
    "baseline": {"baseline_shift", "regime_change"},
    "seasonal": {"seasonal", "repeating_pattern"},
    "trend": {"trend"},
}


class RegistryAnalyzerSelection:
    """Analyzer construction and router-driven selection, shared by SignalPipeline (CSV and
    interactive runs) and MetricAnalysisExecutor (autonomous runs). Both used to carry their own
    copy; the autonomous one hardcoded the 7 built-ins, so an analyzer added through the Add
    Analyzer wizard never ran on scheduled runs. Subclasses provide `self.config`.
    """

    config: AppConfig

    def _build_analyzers(self, analyzer_routing: list[dict[str, object]] | None = None) -> list[Analyzer]:
        """Loads every analyzer registration from config/analyzer_registry.d/ (including the 7
        built-ins, migrated here from a hardcoded if/elif chain, one analyzer at a time - see
        docs/analyzer-recommendation.md) and constructs the ones that are enabled, selected by
        the router, and construct without error.

        config/analyzers.yaml's `analysis.analyzers` block is still consulted, but now only as an
        *override* source - it's what lets config-file toggling (`enabled: false`) and Analyzer
        Labs' "run with custom params" execution-test flow (TimeSeriesRoutingService's
        analyzer_overrides) keep working exactly as before. The registry file's own values are
        the defaults when no override config entry exists for a given analyzer_id.
        """
        allowed = self._allowed_pipeline_analyzers(analyzer_routing or [])
        registrations: list[AnalyzerRegistration] = load_registrations(_REPO_ROOT / "config" / "analyzer_registry.d")
        analyzers: list[Analyzer] = []
        for registration in registrations:
            override_cfg = self.config.analysis.analyzers.get(registration.analyzer_id)
            enabled = override_cfg.enabled if override_cfg is not None else registration.enabled
            if not enabled or not self._should_run_analyzer(registration.analyzer_id, allowed):
                continue
            overrides = self._override_params_for(registration.analyzer_id, override_cfg)
            try:
                analyzers.append(instantiate(registration, overrides=overrides))
            except AnalyzerRegistrationError as exc:
                logger.error(
                    "Skipping analyzer '%s' from %s: %s",
                    registration.analyzer_id,
                    registration.source_file,
                    exc,
                )
        return analyzers

    @staticmethod
    def _apply_analysis_window(analyzers: list[Analyzer], run_metadata: dict[str, object] | None) -> None:
        """Tells analyzers that opt in (by defining set_analysis_window_end) where the requested
        analysis window ends - run_metadata["to"], which Prometheus-backed runs set to the query
        end. Normalized data stops at the last point received, so without this an analyzer can't
        tell that a series went silent before the window ended. Runs with no "to" (CSV uploads,
        OTLP pushes) leave every analyzer untouched. A window end in the future is capped at now,
        so a query range ending later than now isn't mistaken for silence."""
        raw_end = (run_metadata or {}).get("to")
        if not raw_end:
            return
        try:
            window_end = pd.Timestamp(raw_end)
        except (TypeError, ValueError):
            logger.warning("Ignoring unparseable analysis window end %r", raw_end)
            return
        window_end = window_end.tz_localize("UTC") if window_end.tzinfo is None else window_end.tz_convert("UTC")
        window_end = min(window_end, pd.Timestamp(datetime.now(timezone.utc)))
        for analyzer in analyzers:
            setter = getattr(analyzer, "set_analysis_window_end", None)
            if callable(setter):
                setter(window_end)

    def _override_params_for(self, analyzer_id: str, override_cfg: AnalyzerConfig | None) -> dict[str, object]:
        """Translates config/analyzers.yaml's per-analyzer `params` override into the kwarg shape
        each analyzer's constructor actually expects. Most built-in analyzers accept
        `implementation`/`finding_rules` dicts directly, so the raw params dict already matches -
        but baseline_shift and ruptures still take flattened scalar kwargs (a shape inherited
        from the old hardcoded _build_analyzers() chain; see _baseline_shift_params). This is
        narrowly-scoped glue for those two legacy analyzers only - new analyzers registered
        through config/analyzer_registry.d/ should use flat runtime_params from the start and
        won't need any special-casing here.
        """
        if override_cfg is None:
            return {}
        if analyzer_id == "baseline_shift":
            return self._baseline_shift_params(override_cfg.params)
        if analyzer_id == "ruptures":
            flat = self._baseline_shift_params(override_cfg.params)
            return {"min_segment_size": flat["min_segment_size"], "change_threshold": flat["change_threshold"]}
        return override_cfg.params

    def _allowed_pipeline_analyzers(self, analyzer_routing: list[dict[str, object]]) -> set[str] | None:
        selected_router_ids = self._selected_router_analyzers(analyzer_routing)
        if selected_router_ids is None:
            return None

        allowed: set[str] = set()
        router_to_pipeline = self._router_to_pipeline_analyzers()
        for analyzer_id in selected_router_ids:
            allowed.update(router_to_pipeline.get(analyzer_id, {analyzer_id}))
        return allowed

    def _selected_router_analyzers(self, analyzer_routing: list[dict[str, object]]) -> set[str] | None:
        selected = self._selected_by_mode(analyzer_routing)
        if selected is None:
            return None
        return selected | self._always_run_analyzer_ids(analyzer_routing)

    def _always_run_analyzer_ids(self, analyzer_routing: list[dict[str, object]]) -> set[str]:
        """Enabled `always_run` analyzers, minus any the router REJECTED as ineligible for this
        series. One with no router entry at all still runs - it opted out of routing entirely."""
        rejected = {
            str(decision["analyzer_id"])
            for decision in analyzer_routing
            if str(decision.get("recommendation")) == "REJECTED"
        }
        return {
            registration.analyzer_id
            for registration in self._enabled_registrations()
            if registration.always_run and registration.analyzer_id not in rejected
        }

    def _selected_by_mode(self, analyzer_routing: list[dict[str, object]]) -> set[str] | None:
        mode = (self.config.analysis.selection_mode or "all").lower().strip()
        if mode == "all" or not analyzer_routing:
            return None

        selected = set(self.config.analysis.selected_analyzers or [])
        if mode == "manual_override":
            recommended_router_ids = {
                str(decision["analyzer_id"])
                for decision in analyzer_routing
                if str(decision.get("recommendation")) == "RECOMMENDED"
            }
            recommended_router_ids.update(selected)
            return recommended_router_ids

        if mode == "recommended_only":
            return {
                str(decision["analyzer_id"])
                for decision in analyzer_routing
                if str(decision.get("recommendation")) == "RECOMMENDED"
            }

        if mode != "recommended_threshold":
            return None

        execution_config = self.config.analysis.recommendation_execution
        allowed_recommendations = {"RECOMMENDED"}
        if execution_config.include_optional:
            allowed_recommendations.add("OPTIONAL")
        # A router candidate with no real pipeline analyzer behind it (e.g. darts, adtk - see
        # docs/analyzer-recommendation.md, "Router-to-pipeline mapping") must not occupy one of
        # the limited max_analyzers execution slots: a top-scoring but non-executable recommendation
        # would otherwise silently crowd out a lower-scoring one that could actually run and produce
        # a real finding. Eligibility for a slot is filtered here, before ranking - such a candidate
        # can still be RECOMMENDED/OPTIONAL and visible for explanation, it just can't spend a slot.
        #
        # Likewise an analyzer whose optional library isn't installed (requires_library) runs a
        # fallback, not the method the router scored, so it doesn't get a slot either.
        router_to_pipeline = self._router_to_pipeline_analyzers()
        available_pipeline_ids = self._slot_eligible_pipeline_analyzer_ids()
        candidates = [
            (self._decision_score(decision), str(decision["analyzer_id"]))
            for decision in analyzer_routing
            if str(decision.get("recommendation")) in allowed_recommendations
            and self._decision_score(decision) >= execution_config.min_score
            and router_to_pipeline.get(str(decision["analyzer_id"]), {str(decision["analyzer_id"])}) & available_pipeline_ids
        ]
        candidates.sort(key=lambda item: item[0], reverse=True)
        max_analyzers = max(1, execution_config.max_analyzers)
        selected: list[str] = []
        if execution_config.cover_detected_profiles:
            selected = self._profile_coverage(analyzer_routing, router_to_pipeline, available_pipeline_ids)
        for _, analyzer_id in candidates:
            if len(selected) >= max_analyzers:
                break
            if analyzer_id not in selected:
                selected.append(analyzer_id)
        return set(selected)

    @staticmethod
    def _profile_coverage(
        analyzer_routing: list[dict[str, object]],
        router_to_pipeline: dict[str, set[str]],
        available_pipeline_ids: set[str],
    ) -> list[str]:
        """For each problem shape the router detected, the best runnable analyzer built for it.

        Picking purely by score let broad, high-scoring analyzers (a forecaster, a trend fit) take
        every slot, so a series the profiler had flagged as spiky could run no outlier detector at
        all. Each detected profile group gets its highest-scoring runnable analyzer that claims it
        and that the router rated at least OPTIONAL; the remaining slots are then filled by score.
        Coverage picks are kept even past max_analyzers - at most one per group."""
        best: dict[str, tuple[float, str]] = {}
        for decision in analyzer_routing:
            analyzer_id = str(decision["analyzer_id"])
            if str(decision.get("recommendation")) not in {"RECOMMENDED", "OPTIONAL"}:
                continue
            if not router_to_pipeline.get(analyzer_id, {analyzer_id}) & available_pipeline_ids:
                continue
            score = RegistryAnalyzerSelection._decision_score(decision)
            matched = {str(profile) for profile in decision.get("matched_profiles") or []}
            for group, profiles in PROFILE_GROUPS.items():
                if matched & profiles and score > best.get(group, (-1.0, ""))[0]:
                    best[group] = (score, analyzer_id)
        picks: list[str] = []
        for _, analyzer_id in sorted(best.values(), reverse=True):
            if analyzer_id not in picks:
                picks.append(analyzer_id)
        return picks

    def _available_pipeline_analyzer_ids(self) -> set[str]:
        return {registration.analyzer_id for registration in self._enabled_registrations()}

    def _slot_eligible_pipeline_analyzer_ids(self) -> set[str]:
        return {
            registration.analyzer_id
            for registration in self._enabled_registrations()
            if not registration.requires_library or library_installed(registration.requires_library)
        }

    def _enabled_registrations(self) -> list[AnalyzerRegistration]:
        registrations = load_registrations(_REPO_ROOT / "config" / "analyzer_registry.d")
        enabled_registrations: list[AnalyzerRegistration] = []
        for registration in registrations:
            override_cfg = self.config.analysis.analyzers.get(registration.analyzer_id)
            enabled = override_cfg.enabled if override_cfg is not None else registration.enabled
            if enabled:
                enabled_registrations.append(registration)
        return enabled_registrations

    def _executed_analyzer_snapshots(
        self,
        analyzer_routing: list[dict[str, object]],
        executed_analyzers: list[str],
        failed_analyzers: dict[str, str] | None = None,
        selected_analyzers: set[str] | None = None,
    ) -> list[dict[str, object]]:
        failed_analyzers = failed_analyzers or {}
        executed_set = set(executed_analyzers)
        failed_set = set(failed_analyzers)
        selected_router_ids = selected_analyzers
        snapshots = []
        routed_ids = {str(decision.get("analyzer_id")) for decision in analyzer_routing}
        router_to_pipeline = self._router_to_pipeline_analyzers()
        for decision in analyzer_routing:
            router_analyzer_id = str(decision.get("analyzer_id"))
            pipeline_ids = sorted(router_to_pipeline.get(router_analyzer_id, {router_analyzer_id}))
            matching_executed = [pipeline_id for pipeline_id in pipeline_ids if pipeline_id in executed_set]
            matching_failed = [pipeline_id for pipeline_id in pipeline_ids if pipeline_id in failed_set]
            recommended = str(decision.get("recommendation")) == "RECOMMENDED"
            selected = (
                router_analyzer_id in selected_router_ids
                if selected_router_ids is not None
                else bool(recommended and pipeline_ids)
            )
            status = "completed" if matching_executed else "skipped"
            reason = None
            if matching_failed:
                status = "failed"
                reason = "; ".join(f"{pipeline_id}: {failed_analyzers[pipeline_id]}" for pipeline_id in matching_failed)
            if not selected:
                selected = False
                status = "skipped"
                if recommended:
                    reason = "Recommended, but below the execution threshold or capped by max_analyzers."
                elif decision.get("recommendation") == "REJECTED" and decision.get("routing_reason"):
                    reason = str(decision["routing_reason"])
                else:
                    reason = f"Router decision was {decision.get('recommendation')}."
            elif not matching_executed:
                if not matching_failed:
                    reason = "No enabled pipeline analyzer is available for this recommended router analyzer."
            snapshots.append(
                {
                    "router_analyzer_id": router_analyzer_id,
                    "display_name": decision.get("display_name") or router_analyzer_id,
                    "recommendation": decision.get("recommendation"),
                    "selected": selected,
                    "pipeline_analyzer_ids": pipeline_ids,
                    "executed_pipeline_analyzer_ids": matching_executed,
                    "failed_pipeline_analyzer_ids": matching_failed,
                    "execution_status": status,
                    "execution_reason": reason,
                }
            )
        for analyzer_id in executed_analyzers:
            router_analyzer_id = analyzer_id
            if router_analyzer_id in routed_ids:
                continue
            snapshots.append(
                {
                    "router_analyzer_id": router_analyzer_id,
                    "display_name": router_analyzer_id,
                    "recommendation": "UNROUTED",
                    "selected": True,
                    "pipeline_analyzer_ids": [analyzer_id],
                    "executed_pipeline_analyzer_ids": [analyzer_id],
                    "failed_pipeline_analyzer_ids": [],
                    "execution_status": "completed",
                    "execution_reason": None,
                }
            )
        for analyzer_id, error in failed_analyzers.items():
            router_analyzer_id = analyzer_id
            if router_analyzer_id in routed_ids:
                continue
            snapshots.append(
                {
                    "router_analyzer_id": router_analyzer_id,
                    "display_name": router_analyzer_id,
                    "recommendation": "UNROUTED",
                    "selected": True,
                    "pipeline_analyzer_ids": [analyzer_id],
                    "executed_pipeline_analyzer_ids": [],
                    "failed_pipeline_analyzer_ids": [analyzer_id],
                    "execution_status": "failed",
                    "execution_reason": f"{analyzer_id}: {error}",
                }
            )
        return snapshots

    @staticmethod
    def _router_to_pipeline_analyzers() -> dict[str, set[str]]:
        return {"trend_regression": {"trend"}}

    @staticmethod
    def _decision_score(decision: dict[str, object]) -> float:
        try:
            return float(decision.get("final_score") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _analyzer_finding_rules(params: dict[str, object]) -> dict[str, object] | None:
        rules = params.get("finding_rules")
        if isinstance(rules, dict):
            return rules
        legacy_rule = params.get("finding_rule")
        if isinstance(legacy_rule, dict):
            return legacy_rule
        return None

    @staticmethod
    def _analyzer_implementation(params: dict[str, object]) -> dict[str, object] | None:
        implementation = params.get("implementation")
        return implementation if isinstance(implementation, dict) else None

    @staticmethod
    def _baseline_shift_params(params: dict[str, object]) -> dict[str, float | int | str]:
        ruptures_params = params.get("ruptures") if isinstance(params.get("ruptures"), dict) else {}
        finding_rules = params.get("finding_rules") if isinstance(params.get("finding_rules"), dict) else {}
        statistical_gate = params.get("statistical_gate") if isinstance(params.get("statistical_gate"), dict) else {}
        operational_significance = (
            params.get("operational_significance") if isinstance(params.get("operational_significance"), dict) else {}
        )
        return {
            "threshold_percent": float(
                finding_rules.get(  # type: ignore[union-attr]
                    "min_change_percent",
                    operational_significance.get("min_change_percent", params.get("threshold_percent", 25)),  # type: ignore[union-attr]
                )
            ),
            "min_segment_size": int(
                ruptures_params.get("min_size", params.get("min_segment_size", 5))  # type: ignore[union-attr]
            ),
            "change_threshold": float(
                finding_rules.get(  # type: ignore[union-attr]
                    "min_effect_size",
                    statistical_gate.get("min_effect_size", params.get("change_threshold", 1.5)),  # type: ignore[union-attr]
                )
            ),
            "ruptures_algorithm": str(
                ruptures_params.get("algorithm", params.get("ruptures_algorithm", "binseg"))  # type: ignore[union-attr]
            ),
            "ruptures_model": str(
                ruptures_params.get("model", params.get("ruptures_model", "l2"))  # type: ignore[union-attr]
            ),
            "ruptures_jump": int(
                ruptures_params.get("jump", params.get("ruptures_jump", 5))  # type: ignore[union-attr]
            ),
            "ruptures_n_bkps": int(
                ruptures_params.get("n_bkps", params.get("ruptures_n_bkps", 1))  # type: ignore[union-attr]
            ),
        }

    @staticmethod
    def _should_run_analyzer(analyzer_id: str, allowed: set[str] | None) -> bool:
        return allowed is None or analyzer_id in allowed
