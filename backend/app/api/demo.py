"""Demo mode for the web UI (backend/app/demo.py): whether it's on, when the site resets, what the AI
answers are, and the sample files a visitor can analyze instead of uploading their own. The sample
files themselves are offered to everyone (/api/samples), to show what a CSV upload looks like."""

from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.api.ai import _services as ai_services
from backend.app.api.ai import ai_status
from backend.app.api.ingestion import CsvRunOut, _run_csv_upload
from backend.app.demo import get_demo_config, next_reset
from backend.app.models.db import get_db

router = APIRouter(prefix="/api/demo", tags=["demo"])
samples_router = APIRouter(prefix="/api/samples", tags=["samples"])

SAMPLES_DIR = Path(__file__).resolve().parents[3] / "config" / "demo_samples"


class DemoSampleOut(BaseModel):
    id: str
    title: str
    description: str
    service: str
    metric: str


class SampleFileOut(DemoSampleOut):
    file: str
    interval: str
    rows: int
    # The header and first rows, to show the format without downloading.
    preview: list[str]


class DemoOut(BaseModel):
    enabled: bool
    # Show the "Things to try" guide: in demo mode, or on its own with OPS_SIGNALS_DEMO_TOUR.
    tour: bool = False
    resets_at: datetime | None = None
    reset_hours: float | None = None
    run_yourself_url: str | None = None
    # recorded: AI answers were written by a real model when the demo was built (no model runs);
    # live: a model answers now; off: no AI.
    ai: Literal["recorded", "live", "off"] = "off"
    # The model behind the answers: the one that wrote the recorded ones, or the live one.
    ai_model: str | None = None
    samples: list[DemoSampleOut] = []


@lru_cache(maxsize=1)
def _samples() -> tuple[dict, ...]:
    manifest = SAMPLES_DIR / "samples.yml"
    if not manifest.exists():
        return ()
    return tuple((yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}).get("samples") or [])


def _sample(key: str, value: str) -> dict | None:
    return next((item for item in _samples() if item[key] == value), None)


def _sample_lines(sample: dict) -> list[str]:
    return (SAMPLES_DIR / sample["file"]).read_text(encoding="utf-8").splitlines()


def _ai() -> tuple[Literal["recorded", "live", "off"], str | None]:
    status = ai_status()
    if not status.active:
        return "off", None
    if status.provider != "recorded":
        return "live", status.model
    return "recorded", _recorded_model()


def _recorded_model() -> str | None:
    config = ai_services.get("config")
    try:
        entries = json.loads(Path(config.recorded.file).read_text(encoding="utf-8")) if config else []
    except (OSError, ValueError):
        return None
    return next((entry.get("model") for entry in entries if entry.get("model")), None)


@router.get("", response_model=DemoOut)
def demo_status() -> DemoOut:
    config = get_demo_config()
    if not config.enabled:
        return DemoOut(enabled=False, tour=config.tour)
    ai, ai_model = _ai()
    return DemoOut(
        enabled=True,
        tour=True,
        resets_at=next_reset(config),
        reset_hours=config.reset_hours or None,
        run_yourself_url=config.run_yourself_url,
        ai=ai,
        ai_model=ai_model,
        samples=[DemoSampleOut(**{key: sample[key] for key in DemoSampleOut.model_fields}) for sample in _samples()],
    )


@router.post("/samples/{sample_id}", response_model=CsvRunOut)
async def analyze_sample(sample_id: str, db: Session = Depends(get_db)) -> CsvRunOut:
    """Analyze one bundled sample, exactly as if it had been uploaded (New Analysis → CSV). In the
    hosted demo and the local one (the tour on)."""
    config = get_demo_config()
    if not (config.enabled or config.tour):
        raise HTTPException(status_code=404, detail="Samples are only analyzed in the demo")
    sample = _sample("id", sample_id)
    if sample is None:
        raise HTTPException(status_code=404, detail="No such sample")
    data = (SAMPLES_DIR / sample["file"]).read_bytes()
    return await run_in_threadpool(
        _run_csv_upload, data, sample["file"], "generic", sample["service"], sample["metric"], sample["interval"], None, db
    )


@samples_router.get("", response_model=list[SampleFileOut])
def sample_files() -> list[SampleFileOut]:
    """The bundled sample CSVs, with their first rows: what a CSV upload looks like."""
    files = []
    for sample in _samples():
        lines = _sample_lines(sample)
        fields = {key: sample[key] for key in DemoSampleOut.model_fields}
        files.append(SampleFileOut(**fields, file=sample["file"], interval=sample["interval"], rows=max(len(lines) - 1, 0), preview=lines[:4]))
    return files


@samples_router.get("/{file_name}")
def download_sample(file_name: str) -> Response:
    """One sample CSV, as a download. Only the files the manifest lists."""
    sample = _sample("file", file_name)
    if sample is None:
        raise HTTPException(status_code=404, detail="No such sample")
    return Response(
        (SAMPLES_DIR / sample["file"]).read_bytes(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{sample["file"]}"'},
    )
