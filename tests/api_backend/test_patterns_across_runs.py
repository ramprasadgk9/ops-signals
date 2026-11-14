"""Combined patterns from scheduled analyses and OTLP cycles, which analyze each metric in its own
run: rules over several metrics are evaluated across the runs (evaluate_runs_together)."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import select

from backend.app.autonomous import execution, scheduler
from backend.app.behavior_intelligence.service import evaluate_runs_together
from backend.app.models.db import get_session_local
from backend.app.models.entities import BehaviorFindingEntity, SignalEntity

CHANGE_AT = datetime(2026, 10, 21, 15, 50, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 10, 21, 19, 45, tzinfo=timezone.utc)


def _ruptures(db, run_id: str, metric: str, percent: float, service: str = "payments-db") -> None:
    """The level-change signal a run leaves for a metric that went up by `percent`."""
    db.add(
        SignalEntity(
            signal_id=uuid4().hex,
            signal_type="ruptures",
            analyzer_id="ruptures",
            metric_name=metric,
            service=service,
            severity="high",
            confidence=0.9,
            start_time=CHANGE_AT,
            end_time=WINDOW_END,
            summary=f"{metric} went up",
            evidence_json={"percent_change": percent},
            importance_score=0.8,
            analysis_run_id=run_id,
        )
    )
    db.commit()


def _pool_runs(db, wait_run: str = "run-wait", active_run: str = "run-active", service: str = "payments-db") -> list[str]:
    """Connection wait and active connections both went up, each found by its own run."""
    _ruptures(db, wait_run, "db_connection_wait_seconds", 131.5, service)
    _ruptures(db, active_run, "db_connections_active", 49.0, service)
    return [wait_run, active_run]


def _patterns(db) -> list[BehaviorFindingEntity]:
    return list(db.execute(select(BehaviorFindingEntity)).scalars())


def test_a_pattern_over_two_metrics_matches_across_their_runs(db_session) -> None:
    runs = _pool_runs(db_session)

    assert evaluate_runs_together(db_session, runs) == 1

    [pattern] = _patterns(db_session)
    assert pattern.definition_id == "pool_exhaustion"
    assert pattern.service == "payments-db"
    # Stored under the first input's run, with every input's run listed.
    assert pattern.analysis_run_id == "run-wait"
    assert pattern.correlation_json["analysis_run_ids"] == ["run-wait", "run-active"]


def test_metrics_of_different_services_are_not_combined(db_session) -> None:
    _ruptures(db_session, "run-wait", "db_connection_wait_seconds", 131.5, service="payments-db")
    _ruptures(db_session, "run-active", "db_connections_active", 49.0, service="orders-db")

    assert evaluate_runs_together(db_session, ["run-wait", "run-active"]) == 0
    assert _patterns(db_session) == []


def test_a_match_inside_one_run_is_left_to_that_run(db_session) -> None:
    # A CSV upload analyzes both metrics in one run and evaluates the rules itself; counting it
    # again here would bump the pattern twice.
    _pool_runs(db_session, wait_run="csv-run", active_run="csv-run")
    _ruptures(db_session, "other-run", "cpu_usage", 10.0)

    assert evaluate_runs_together(db_session, ["csv-run", "other-run"]) == 0
    assert evaluate_runs_together(db_session, ["csv-run"]) == 0


def test_metrics_that_did_not_both_change_make_no_pattern(db_session) -> None:
    _ruptures(db_session, "run-wait", "db_connection_wait_seconds", 131.5)
    _ruptures(db_session, "run-cpu", "cpu_usage", 40.0)

    assert evaluate_runs_together(db_session, ["run-wait", "run-cpu"]) == 0


def test_the_next_scheduled_run_bumps_the_same_pattern_and_points_at_its_runs(db_session) -> None:
    evaluate_runs_together(db_session, _pool_runs(db_session))
    evaluate_runs_together(db_session, _pool_runs(db_session, wait_run="run-wait-2", active_run="run-active-2"))

    [pattern] = _patterns(db_session)
    assert pattern.occurrence_count == 2
    assert pattern.correlation_json["analysis_run_ids"] == ["run-wait-2", "run-active-2"]


def test_a_failure_never_breaks_the_analysis_it_follows(db_session) -> None:
    runs = _pool_runs(db_session)
    with patch("backend.app.behavior_intelligence.service.BehaviorIntelligenceService.evaluate_across_runs", side_effect=RuntimeError("boom")):
        assert evaluate_runs_together(db_session, runs) == 0


def test_the_api_lists_the_pattern_under_each_of_its_runs(client) -> None:
    with get_session_local()() as db:
        evaluate_runs_together(db, _pool_runs(db))

    for run in ("run-wait", "run-active"):
        response = client.get("/api/behavior-evaluations", params={"analysis_run_id": run})
        assert response.status_code == 200
        [pattern] = response.json()
        assert pattern["analysis_run_ids"] == ["run-wait", "run-active"]
    assert client.get("/api/behavior-evaluations", params={"analysis_run_id": "run-wai"}).json() == []


def test_a_single_run_pattern_lists_its_own_run(client) -> None:
    with get_session_local()() as db:
        db.add(
            BehaviorFindingEntity(
                behavior_id="pool_exhaustion:2:csv-run",
                definition_id="pool_exhaustion",
                definition_version=2,
                title="Database connection pool exhaustion",
                summary="Pool full",
                category="resource_constraint",
                severity="critical",
                service="payments-db",
                analysis_run_id="csv-run",
            )
        )
        db.commit()

    [pattern] = client.get("/api/behavior-evaluations", params={"analysis_run_id": "csv-run"}).json()
    assert pattern["analysis_run_ids"] == ["csv-run"]


def test_a_scheduled_run_evaluates_patterns_across_its_completed_jobs(db_session) -> None:
    completed = [
        SimpleNamespace(status="completed", analysis_run_id=run, findings_count=1, behavior_findings_count=0, not_checked=False, error=None)
        for run in ("run-wait", "run-active")
    ]
    failed = SimpleNamespace(status="failed", analysis_run_id=None, findings_count=0, behavior_findings_count=0, not_checked=False, error="no samples")
    items = [SimpleNamespace(planned=True, metric_name=f"m{index}", exclusion_reason=None) for index in range(3)]
    preview = SimpleNamespace(
        items=items, budget_limited_jobs=0, budget_excluded_metrics=[], budget_excluded_metrics_count=0, warnings=[],
        scope_summary={}, monitoring_summary={}, metrics_discovered=3, metrics_selected=3, planned_jobs=3,
    )
    with (
        patch.object(execution, "_execute_plan_item", side_effect=[*completed, failed]),
        patch.object(execution, "_create_jobs", return_value={id(item): SimpleNamespace(id=f"job-{index}") for index, item in enumerate(items)}),
        patch.object(execution, "evaluate_runs_together", return_value=1) as evaluate,
        patch.object(execution, "AutonomousRunResponse", side_effect=lambda **kwargs: kwargs),
    ):
        response = execution.execute_autonomous_plan_once(
            preview=preview, prometheus=None, db=db_session, config=None, analysis_window="6h", step="1m", drilldown=None
        )

    evaluate.assert_called_once_with(db_session, ["run-wait", "run-active"])
    # The pattern counts toward the run's findings: two single-metric findings plus the pattern.
    assert response["summary"]["findings_created"] == 3


def test_an_otlp_cycle_evaluates_patterns_across_the_series_it_analyzed() -> None:
    due = [("payments-db", "db_connection_wait_seconds", 60), ("payments-db", "db_connections_active", 60), ("orders", "orders_failed", 60)]
    with (
        patch.object(scheduler, "get_session_local", return_value=lambda: _NullSession()),
        patch.object(scheduler, "_due_otlp_groups", return_value=due),
        patch.object(scheduler, "_analyze_otlp_group", side_effect=["run-wait", "run-active", None]),
        patch.object(scheduler, "evaluate_runs_together") as evaluate,
    ):
        scheduler._analyze_pending_otlp()

    # The failed series (None) is left out.
    assert evaluate.call_args.args[1] == ["run-wait", "run-active"]


class _NullSession:
    """Just enough of a Session for the OTLP cycle with its database calls patched out."""

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None

    def query(self, *args):
        return self

    def filter(self, *args):
        return self

    def order_by(self, *args):
        return self

    def all(self):
        return []
