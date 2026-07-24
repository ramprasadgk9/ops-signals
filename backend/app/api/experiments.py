from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.app.experiments.service import ExperimentComparisonService, ExperimentResultRepository, ExperimentService

router = APIRouter(prefix="/api/experiments", tags=["experiments"])

service = ExperimentService(ExperimentResultRepository())
comparison_service = ExperimentComparisonService()


@router.get("")
def list_experiments():
    return service.list_experiments()


@router.get("/compare")
def compare_experiments(experiment_ids: list[str] = Query(default_factory=list)):
    experiments = []
    for experiment_id in experiment_ids:
        try:
            experiments.append(service.get_experiment(experiment_id))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"experiment not found: {experiment_id}") from exc
    return comparison_service.compare(experiments)


@router.get("/{experiment_id}")
def get_experiment(experiment_id: str):
    try:
        return service.get_experiment(experiment_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="experiment not found") from exc
