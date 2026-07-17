from __future__ import annotations

import copy
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.api_schema import CsvRunOut
from backend.app.models.db import get_db
from backend.app.models.entities import FindingEntity
from intelligence.config import load_config
from intelligence.pipeline import SignalPipeline

router = APIRouter(prefix="/api/ingestion", tags=["ingestion"])


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _provider_defaults(provider: str) -> tuple[dict[str, str], list[str]]:
    provider_lower = provider.lower()
    if provider_lower == "prometheus":
        return ({"metric_name": "metric", "host": "instance"}, ["timestamp", "metric", "value"])
    if provider_lower == "datadog":
        return ({"timestamp": "ts_epoch_ms"}, ["ts_epoch_ms", "metric_name", "value"])
    return ({}, ["timestamp", "metric_name", "value"])


@router.post("/csv-run", response_model=CsvRunOut)
async def run_csv_analysis(
    file: UploadFile = File(...),
    provider: str = Form(default="generic"),
    service: str = Form(default="uploaded-service"),
    metric_name: str = Form(default="uploaded_metric"),
    interval: str = Form(default="5m"),
    db: Session = Depends(get_db),
) -> CsvRunOut:
    provider_lower = provider.lower()
    if provider_lower not in {"generic", "prometheus", "datadog"}:
        raise HTTPException(status_code=400, detail="provider must be one of: generic, prometheus, datadog")
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="only .csv uploads are supported")

    upload_dir = _repo_root() / ".tmp_uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    suffix = Path(file.filename).suffix or ".csv"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=upload_dir) as handle:
        temp_path = Path(handle.name)
        data = await file.read()
        handle.write(data)

    mapping_defaults, required_defaults = _provider_defaults(provider_lower)

    try:
        template_config = load_config(_repo_root() / "config.yaml")
        config = copy.deepcopy(template_config)

        config.input.source_type = "csv"
        config.input.provider = provider_lower
        config.input.file_path = str(temp_path)
        config.input.interval = interval
        config.input.service = service
        config.input.metric_name = metric_name
        config.input.provider_mappings = mapping_defaults
        config.input.required_columns = required_defaults
        config.input.timestamp_column = "timestamp"
        config.input.value_column = "value"
        config.input.metric_column = "metric_name"

        config.output.save_normalized_data = True
        config.output.save_signals = True
        config.output.save_question_answers = True
        config.output.save_embeddings = False
        config.embeddings.enabled = False

        result = SignalPipeline(config).run()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"analysis failed: {exc}") from exc
    finally:
        temp_path.unlink(missing_ok=True)

    # Query findings from database instead of relying on in-memory result
    findings_count = db.execute(
        select(func.count(FindingEntity.id)).where(FindingEntity.analysis_run_id == result.analysis_run_id)
    ).scalar() or 0

    normalized = result.normalized_points
    return CsvRunOut(
        analysis_run_id=result.analysis_run_id,
        provider=provider_lower,
        source_type="csv",
        service=service,
        metric_name=metric_name,
        sample_count=int(len(normalized)),
        findings_count=int(findings_count),
    )
