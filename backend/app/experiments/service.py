from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.experiments.schemas import (
    ExperimentComparisonOut,
    ExperimentResultOut,
)


class ExperimentResultRepository:
    def __init__(self, root_dir: str | Path = "experiments/ruptures/results") -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def list_results(self) -> list[ExperimentResultOut]:
        results = []
        for path in sorted(self.root_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            results.append(self.load_result(path.stem))
        return results

    def load_result(self, experiment_id: str) -> ExperimentResultOut:
        path = self.root_dir / f"{experiment_id}.json"
        if not path.exists():
            raise FileNotFoundError(experiment_id)
        return ExperimentResultOut.model_validate_json(path.read_text())

    def save_result(self, result: ExperimentResultOut) -> ExperimentResultOut:
        path = self.root_dir / f"{result.experiment_id}.json"
        path.write_text(result.model_dump_json(indent=2))
        return result


class ExperimentService:
    def __init__(self, repository: ExperimentResultRepository | None = None) -> None:
        self.repository = repository or ExperimentResultRepository()

    def list_experiments(self) -> list[ExperimentResultOut]:
        return self.repository.list_results()

    def get_experiment(self, experiment_id: str) -> ExperimentResultOut:
        return self.repository.load_result(experiment_id)

    def save_experiment(self, result: ExperimentResultOut) -> ExperimentResultOut:
        return self.repository.save_result(result)


class ExperimentComparisonService:
    def compare(self, experiments: list[ExperimentResultOut]) -> ExperimentComparisonOut:
        if not experiments:
            raise ValueError("No experiments to compare")
        analyzer = experiments[0].analyzer.name
        events_by_signature: dict[str, list[str]] = {}
        for experiment in experiments:
            for event in experiment.results.events:
                signature = f"{event.event_type}:{event.index}:{event.timestamp}"
                events_by_signature.setdefault(signature, []).append(experiment.experiment_id)
        shared_event_count = sum(1 for ids in events_by_signature.values() if len(ids) > 1)
        unique_event_count = sum(1 for ids in events_by_signature.values() if len(ids) == 1)
        summary = self._build_summary(experiments, shared_event_count, unique_event_count)
        return ExperimentComparisonOut(
            analyzer=analyzer,
            comparison_summary=summary,
            shared_event_count=shared_event_count,
            unique_event_count=unique_event_count,
            experiment_ids=[experiment.experiment_id for experiment in experiments],
            items=[
                {
                    "experiment_id": experiment.experiment_id,
                    "penalty": experiment.analyzer.parameters.get("penalty"),
                    "event_count": experiment.results.event_count,
                    "summary": experiment.plain_language_summary,
                }
                for experiment in experiments
            ],
        )

    def _build_summary(self, experiments: list[ExperimentResultOut], shared_event_count: int, unique_event_count: int) -> str:
        sorted_experiments = sorted(experiments, key=lambda item: item.analyzer.parameters.get("penalty", 0))
        low = sorted_experiments[0]
        high = sorted_experiments[-1]
        return (
            f"{len(experiments)} experiments were compared. "
            f"{shared_event_count} events were stable across multiple configurations, while {unique_event_count} appeared only in one run. "
            f"Lower penalties such as {low.analyzer.parameters.get('penalty')} usually surfaced more events, "
            f"while higher penalties such as {high.analyzer.parameters.get('penalty')} produced simpler explanations."
        )
