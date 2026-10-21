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
from intelligence.findings.schema import OperationalFinding
from intelligence.signals.schema import OperationalSignal

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
SHAPE_NAMES = {"spike": "spikes", "baseline": "baseline shift", "seasonal": "seasonal pattern", "trend": "trend"}

# Why an analyzer was set to run (the first group) or didn't run (the second), as recorded on each
# analyzer execution snapshot's `run_reason`. The text is the default explanation shown with it.
RUN_REASON_TEXT = {
    "router_pick": "Picked by the router for this series.",
    "covers_shape": "Ran to cover a shape the router detected in this series.",
    "spike_fallback": "Ran as the spike detector: the series looks spiky and nothing else selected looks for spikes.",
    "always_run": "Runs on every series.",
    "runs_all": "Runs because analysis is set to run every analyzer.",
    "chosen_in_settings": "Chosen in the analysis settings.",
    "not_built_in": "In the router's catalog, but not built into Ops Signals yet, so it can't run.",
    "turned_off": "Turned off in the analyzer settings.",
    "library_missing": "Its library isn't installed, so it doesn't run.",
    "rejected": "The router ruled it out for this series.",
    "not_selected": "Not chosen for this run.",
    "router_failed": "The router couldn't score this series.",
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
        reasons = self._selection_reasons(analyzer_routing)
        return None if reasons is None else set(reasons)

    def _selection_reasons(self, analyzer_routing: list[dict[str, object]]) -> dict[str, str] | None:
        """Router analyzer id -> why it was set to run (a RUN_REASON_TEXT key), or None when the
        selection mode runs every enabled analyzer. The ids are exactly _selected_router_analyzers'."""
        reasons = self._selected_by_mode(analyzer_routing)
        if reasons is None:
            return None
        for analyzer_id in sorted(self._always_run_analyzer_ids(analyzer_routing)):
            reasons.setdefault(analyzer_id, "always_run")
        return reasons

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

    def _selected_by_mode(self, analyzer_routing: list[dict[str, object]]) -> dict[str, str] | None:
        mode = (self.config.analysis.selection_mode or "all").lower().strip()
        if mode == "all" or not analyzer_routing:
            return None

        recommended_router_ids = [
            str(decision["analyzer_id"])
            for decision in analyzer_routing
            if str(decision.get("recommendation")) == "RECOMMENDED"
        ]
        if mode == "manual_override":
            reasons = dict.fromkeys(recommended_router_ids, "router_pick")
            for analyzer_id in self.config.analysis.selected_analyzers or []:
                reasons.setdefault(analyzer_id, "chosen_in_settings")
            return reasons

        if mode == "recommended_only":
            return dict.fromkeys(recommended_router_ids, "router_pick")

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
        # A coverage pick that also scored well enough on its own reads as a router pick: coverage
        # is only the reason when the router rated it too low to be chosen by score.
        scored_ids = {analyzer_id for _, analyzer_id in candidates}
        reasons = {
            analyzer_id: "router_pick" if analyzer_id in scored_ids else "covers_shape"
            for analyzer_id in selected
        }
        if execution_config.cover_detected_profiles:
            fallback = self._spike_fallback(analyzer_routing, selected, available_pipeline_ids)
            if fallback:
                reasons[fallback] = "spike_fallback"
        return reasons

    @staticmethod
    def _spike_fallback(
        analyzer_routing: list[dict[str, object]],
        selected: list[str],
        available_pipeline_ids: set[str],
    ) -> str | None:
        """A spike detector for a series the profiler flagged as spiky when nothing selected covers
        spikes (QA-29). PyOD Outlier when the router only scored it low; Z-Score only when the series
        has fewer points than PyOD needs (50), since Z-Score needs 3. Z-Score stays out otherwise,
        including when PyOD was rejected for gaps or bad values: on long series it raises far more
        false alarms than PyOD (docs/analyzers-explained.md)."""
        spike_profiles = PROFILE_GROUPS["spike"]
        detected = {
            str(profile)
            for decision in analyzer_routing
            for profile in (decision.get("parameters_tested") or {}).get("detected_profiles") or []
        }
        if not detected & spike_profiles:
            return None
        by_id = {str(decision["analyzer_id"]): decision for decision in analyzer_routing}
        for analyzer_id in selected:
            if {str(profile) for profile in by_id.get(analyzer_id, {}).get("matched_profiles") or []} & spike_profiles:
                return None
        pyod = by_id.get("pyod_outlier")
        if pyod is not None and str(pyod.get("recommendation")) != "REJECTED" and "pyod_outlier" in available_pipeline_ids:
            return "pyod_outlier"
        pyod_tested = (pyod or {}).get("parameters_tested") or {}
        sample_count = pyod_tested.get("valid_sample_count")
        pyod_minimum = int((pyod_tested.get("eligibility_rules") or {}).get("min_samples") or 50)
        if isinstance(sample_count, int) and sample_count < pyod_minimum and "anomaly_zscore" in available_pipeline_ids:
            return "anomaly_zscore"
        return None

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
        """One record per router candidate (plus any analyzer that ran without a router entry):
        what happened to it and why. `run_reason` is a RUN_REASON_TEXT key - for one set to run,
        why it was chosen; for one that wasn't, why not. The web UI and the Grafana
        plugin show these, so they never have to guess why an analyzer ran."""
        failed_analyzers = failed_analyzers or {}
        executed_set = set(executed_analyzers)
        failed_set = set(failed_analyzers)
        selected_router_ids = selected_analyzers
        selection_reasons = self._selection_reasons(analyzer_routing) or {}
        snapshots = []
        router_to_pipeline = self._router_to_pipeline_analyzers()
        # Pipeline ids a router decision already reports on (trend_regression -> trend), so an
        # aliased analyzer isn't listed a second time as unrouted.
        routed_ids = {
            pipeline_id
            for decision in analyzer_routing
            for pipeline_id in router_to_pipeline.get(str(decision.get("analyzer_id")), {str(decision.get("analyzer_id"))})
        }
        registrations = {registration.analyzer_id: registration for registration in load_registrations(_REPO_ROOT / "config" / "analyzer_registry.d")}
        available_ids = self._available_pipeline_analyzer_ids()
        slot_eligible_ids = self._slot_eligible_pipeline_analyzer_ids()
        for decision in analyzer_routing:
            router_analyzer_id = str(decision.get("analyzer_id"))
            pipeline_ids = sorted(router_to_pipeline.get(router_analyzer_id, {router_analyzer_id}))
            matching_executed = [pipeline_id for pipeline_id in pipeline_ids if pipeline_id in executed_set]
            matching_failed = [pipeline_id for pipeline_id in pipeline_ids if pipeline_id in failed_set]
            recommended = str(decision.get("recommendation")) == "RECOMMENDED"
            selected = (
                router_analyzer_id in selected_router_ids
                if selected_router_ids is not None
                # Every enabled analyzer runs in "all" mode, so whatever ran was selected.
                else bool((recommended and pipeline_ids) or matching_executed or matching_failed)
            )
            status = "completed" if matching_executed else "skipped"
            reason = None
            missing_library = None
            if matching_failed:
                status = "failed"
                reason = "; ".join(f"{pipeline_id}: {failed_analyzers[pipeline_id]}" for pipeline_id in matching_failed)
            if not selected:
                selected = False
                status = "skipped"
                run_reason, missing_library = self._skip_reason(
                    router_analyzer_id, decision, pipeline_ids, registrations, available_ids, slot_eligible_ids
                )
                if recommended and not set(pipeline_ids) & available_ids:
                    # e.g. adtk, darts: the router scores them, but nothing in the pipeline runs them.
                    reason = "Recommended, but no pipeline analyzer implements it yet, so it can't run; the score is for reference."
                elif recommended and not set(pipeline_ids) & slot_eligible_ids:
                    reason = "Recommended, but its library isn't installed, so it doesn't run."
                elif recommended:
                    reason = "Recommended, but below the execution threshold or capped by max_analyzers."
                elif decision.get("recommendation") == "REJECTED" and decision.get("routing_reason"):
                    reason = str(decision["routing_reason"])
                else:
                    reason = f"Router decision was {decision.get('recommendation')}."
            else:
                run_reason = self._run_reason(router_analyzer_id, selection_reasons, registrations, selected_router_ids)
                if not matching_executed:
                    if not matching_failed:
                        reason = "No enabled pipeline analyzer is available for this recommended router analyzer."
                else:
                    reason = self._run_reason_text(run_reason, router_analyzer_id, analyzer_routing, decision)
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
                    "run_reason": run_reason,
                    "shapes": self._matched_shapes(decision),
                    "missing_library": missing_library,
                    "in_finding": None,
                    "description": self._description(pipeline_ids, registrations),
                }
            )
        for analyzer_id in executed_analyzers:
            router_analyzer_id = analyzer_id
            if router_analyzer_id in routed_ids:
                continue
            run_reason = self._run_reason(analyzer_id, selection_reasons, registrations, selected_router_ids)
            registration = registrations.get(analyzer_id)
            snapshots.append(
                {
                    "router_analyzer_id": router_analyzer_id,
                    "display_name": registration.display_name if registration else router_analyzer_id,
                    "recommendation": "UNROUTED",
                    "selected": True,
                    "pipeline_analyzer_ids": [analyzer_id],
                    "executed_pipeline_analyzer_ids": [analyzer_id],
                    "failed_pipeline_analyzer_ids": [],
                    "execution_status": "completed",
                    "execution_reason": self._run_reason_text(run_reason, analyzer_id, analyzer_routing, {}),
                    "run_reason": run_reason,
                    "shapes": [],
                    "missing_library": None,
                    "in_finding": None,
                    "description": self._description([analyzer_id], registrations),
                }
            )
        for analyzer_id, error in failed_analyzers.items():
            router_analyzer_id = analyzer_id
            if router_analyzer_id in routed_ids:
                continue
            registration = registrations.get(analyzer_id)
            snapshots.append(
                {
                    "router_analyzer_id": router_analyzer_id,
                    "display_name": registration.display_name if registration else router_analyzer_id,
                    "recommendation": "UNROUTED",
                    "selected": True,
                    "pipeline_analyzer_ids": [analyzer_id],
                    "executed_pipeline_analyzer_ids": [],
                    "failed_pipeline_analyzer_ids": [analyzer_id],
                    "execution_status": "failed",
                    "execution_reason": f"{analyzer_id}: {error}",
                    "run_reason": self._run_reason(analyzer_id, selection_reasons, registrations, selected_router_ids),
                    "shapes": [],
                    "missing_library": None,
                    "in_finding": None,
                    "description": self._description([analyzer_id], registrations),
                }
            )
        return snapshots

    @staticmethod
    def _mark_finding_contributors(
        snapshots: list[dict[str, object]],
        signals: list[OperationalSignal],
        findings: list[OperationalFinding],
    ) -> None:
        """Sets `in_finding` on every analyzer that ran: True when at least one of its signals is
        part of a finding. One finding can merge several analyzers' signals, so this says which
        analyzers fed the run's findings, never how many findings each one produced."""
        analyzer_by_signal = {signal.signal_id: signal.analyzer_id for signal in signals}
        contributors = {
            analyzer_by_signal[signal_id]
            for finding in findings
            for signal_id in finding.signal_ids
            if signal_id in analyzer_by_signal
        }
        for snapshot in snapshots:
            executed_ids = snapshot.get("executed_pipeline_analyzer_ids") or []
            if executed_ids:
                snapshot["in_finding"] = bool(contributors & set(executed_ids))  # type: ignore[arg-type]

    @staticmethod
    def _description(pipeline_ids: list[str], registrations: dict[str, AnalyzerRegistration]) -> str | None:
        """What the analyzer does in plain words, from its registration; None for a router
        candidate that isn't built in."""
        return next(
            (registrations[pipeline_id].description for pipeline_id in pipeline_ids if pipeline_id in registrations and registrations[pipeline_id].description),
            None,
        )

    @staticmethod
    def _run_reason(
        analyzer_id: str,
        selection_reasons: dict[str, str],
        registrations: dict[str, AnalyzerRegistration],
        selected_router_ids: set[str] | None,
    ) -> str:
        if analyzer_id in selection_reasons:
            return selection_reasons[analyzer_id]
        registration = registrations.get(analyzer_id)
        if registration is not None and registration.always_run:
            return "always_run"
        if selected_router_ids is None:
            return "runs_all"
        return "router_pick"

    @staticmethod
    def _skip_reason(
        analyzer_id: str,
        decision: dict[str, object],
        pipeline_ids: list[str],
        registrations: dict[str, AnalyzerRegistration],
        available_ids: set[str],
        slot_eligible_ids: set[str],
    ) -> tuple[str, str | None]:
        """Why a router candidate didn't run, and the missing library's name when that's why."""
        if analyzer_id == "router":
            return "router_failed", None
        if not set(pipeline_ids) & set(registrations):
            return "not_built_in", None
        if not set(pipeline_ids) & available_ids:
            return "turned_off", None
        if not set(pipeline_ids) & slot_eligible_ids:
            libraries = [registrations[pipeline_id].requires_library for pipeline_id in pipeline_ids if pipeline_id in registrations]
            return "library_missing", next((library for library in libraries if library), None)
        if str(decision.get("recommendation")) == "REJECTED":
            return "rejected", None
        return "not_selected", None

    def _run_reason_text(
        self,
        run_reason: str,
        analyzer_id: str,
        analyzer_routing: list[dict[str, object]],
        decision: dict[str, object],
    ) -> str:
        if run_reason == "spike_fallback":
            return self._spike_fallback_reason(analyzer_id, analyzer_routing) or RUN_REASON_TEXT["spike_fallback"]
        if run_reason == "covers_shape":
            shapes = self._matched_shapes(decision)
            if shapes:
                return f"Ran to cover the {' and '.join(SHAPE_NAMES[shape] for shape in shapes)} the router detected."
        return RUN_REASON_TEXT.get(run_reason, RUN_REASON_TEXT["router_pick"])

    @staticmethod
    def _matched_shapes(decision: dict[str, object]) -> list[str]:
        """The PROFILE_GROUPS the router matched this analyzer to, in PROFILE_GROUPS order."""
        matched = {str(profile) for profile in decision.get("matched_profiles") or []}  # type: ignore[union-attr]
        return [group for group, profiles in PROFILE_GROUPS.items() if matched & profiles]

    def _spike_fallback_reason(self, analyzer_id: str, analyzer_routing: list[dict[str, object]]) -> str | None:
        """Why a spike detector ran that the router didn't pick itself (see _spike_fallback)."""
        if analyzer_id not in {"pyod_outlier", "anomaly_zscore"}:
            return None
        if (self.config.analysis.selection_mode or "").lower().strip() != "recommended_threshold":
            return None
        if analyzer_id in set(self.config.analysis.selected_analyzers or []):
            return None
        detected = {
            str(profile)
            for decision in analyzer_routing
            for profile in (decision.get("parameters_tested") or {}).get("detected_profiles") or []
        }
        if not detected & PROFILE_GROUPS["spike"]:
            return None
        if analyzer_id == "anomaly_zscore":
            return "Ran as the spike detector: the series looks spiky and PyOD Outlier needs at least 50 points."
        return "Ran as the spike detector: the series looks spiky and nothing else selected looks for spikes."

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
