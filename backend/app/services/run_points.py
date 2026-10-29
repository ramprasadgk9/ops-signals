"""Stored points by series, not by run.

A scheduled run fetches its whole analysis window again each time (the analyzers need all of it),
but only the points newer than the series' last stored point are saved, like a Prometheus
recording rule appends only its new evaluation. A run's points are then its series' points
between the run's start and end time, whichever run saved them. Runs from before series keys
(and CSV and OTLP runs) keep their own copy, found by run id as before.
"""

from __future__ import annotations

from hashlib import sha256

from sqlalchemy import and_
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from backend.app.models.entities import AnalysisRunEntity, NormalizedPoint


def series_key(connection_id: str, promql: str) -> str:
    """One stored series per connection (Mimir tenant) and query: the query's result is the series,
    as a recording rule's expression is."""
    return sha256(f"{connection_id}\n{promql}".encode()).hexdigest()[:32]


def run_points_filter(db: Session, analysis_run_id: str) -> ColumnElement[bool]:
    """Where-clause for the points a run analyzed."""
    run = db.get(AnalysisRunEntity, analysis_run_id)
    if run is None or not run.series_key:
        return NormalizedPoint.analysis_run_id == analysis_run_id
    return and_(
        NormalizedPoint.series_key == run.series_key,
        NormalizedPoint.timestamp >= run.start_time,
        NormalizedPoint.timestamp <= run.end_time,
    )
