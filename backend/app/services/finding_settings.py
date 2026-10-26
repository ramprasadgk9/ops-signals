"""Which per-service analyzer settings (config/analyzer_overrides.d/) a finding was made with.

A run records, per analyzer, the overrides that changed it and for which series
(executed_analyzers_json[*].settings_overrides, see RegistryAnalyzerSelection._series_snapshots).
A finding used custom settings when an analyzer behind one of its signals was changed for the
finding's own service and metric.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.entities import AnalysisRunEntity, FindingEntity, SignalEntity

_CHUNK = 500


def finding_custom_settings(db: Session, rows: list[FindingEntity]) -> dict[int, dict[str, Any]]:
    """Finding id -> {"settings": [...], "overrides": [...]}, only for findings made with custom
    settings. Two queries at most, and one when no run in the list used any."""
    run_ids = sorted({row.analysis_run_id for row in rows if row.analysis_run_id})
    if not run_ids:
        return {}
    tuned_runs = {
        run_id: [snapshot for snapshot in executed or [] if snapshot.get("settings_overrides")]
        for run_id, executed in db.execute(
            select(AnalysisRunEntity.id, AnalysisRunEntity.executed_analyzers_json).where(AnalysisRunEntity.id.in_(run_ids))
        ).all()
    }
    tuned_runs = {run_id: snapshots for run_id, snapshots in tuned_runs.items() if snapshots}
    if not tuned_runs:
        return {}

    tuned_rows = [row for row in rows if row.id is not None and row.analysis_run_id in tuned_runs]
    signal_ids = sorted({signal_id for row in tuned_rows for signal_id in (row.signal_ids or [])})
    analyzer_by_signal: dict[str, str] = {}
    for start in range(0, len(signal_ids), _CHUNK):
        chunk = signal_ids[start : start + _CHUNK]
        analyzer_by_signal.update(
            db.execute(select(SignalEntity.signal_id, SignalEntity.analyzer_id).where(SignalEntity.signal_id.in_(chunk))).all()
        )

    result: dict[int, dict[str, Any]] = {}
    for row in tuned_rows:
        analyzers = {analyzer_by_signal[signal_id] for signal_id in (row.signal_ids or []) if signal_id in analyzer_by_signal}
        series = {"service": row.service, "metric": row.metric_name}
        settings: list[dict[str, Any]] = []
        overrides: dict[str, dict[str, Any]] = {}
        for snapshot in tuned_runs[row.analysis_run_id]:
            for entry in snapshot["settings_overrides"]:
                if series not in (entry.get("series") or []):
                    continue
                used = [setting for setting in entry.get("settings") or [] if setting.get("analyzer_id") in analyzers]
                if not used:
                    continue
                settings.extend(setting for setting in used if setting not in settings)
                for override in entry.get("overrides") or []:
                    overrides.setdefault(str(override.get("id")), override)
        if settings:
            result[row.id] = {"settings": settings, "overrides": list(overrides.values())}
    return result
