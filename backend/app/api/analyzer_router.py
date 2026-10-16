from __future__ import annotations

import json
import logging
import tempfile
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from experiments.analyzer_router.config_loader import build_request
from experiments.analyzer_router.router import UniversalTimeSeriesRouter

router = APIRouter(prefix="/api/experiment-analyzer-router", tags=["experiment-analyzer-router"])
logger = logging.getLogger(__name__)


@router.post("/route")
async def route_analyzers(
    file: UploadFile = File(...),
    timestamp_column: str | None = Form(default=None),
    value_column: str | None = Form(default=None),
    routing_mode: str = Form(default="automatic_with_override"),
    selected_analyzers: str = Form(default=""),
):
    data = await file.read()
    # Profiling the series blocks: run it off the event loop.
    return await run_in_threadpool(
        _route_upload, data, file.filename, timestamp_column, value_column, routing_mode, selected_analyzers
    )


def _route_upload(
    data: bytes,
    file_name: str | None,
    timestamp_column: str | None,
    value_column: str | None,
    routing_mode: str,
    selected_analyzers: str,
):
    try:
        suffix = Path(file_name or "upload.csv").suffix or ".csv"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)

        router_service = UniversalTimeSeriesRouter()
        request = build_request(
            {
                "csv_path": str(tmp_path),
                "timestamp_column": timestamp_column,
                "value_column": value_column,
                "routing_mode": routing_mode,
                "selected_analyzers": [item.strip() for item in selected_analyzers.split(",") if item.strip()],
            }
        )
        result = router_service.route(request)
        payload = {
            "summary": result.summary,
            "validation": asdict(result.validation),
            "profile": asdict(result.profile),
            "analyzers": [asdict(decision) for decision in result.analyzers],
            "export_path": result.export_path,
        }
        return json.loads(json.dumps(payload, default=str))
    except Exception as exc:
        logger.exception("Analyzer router failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
