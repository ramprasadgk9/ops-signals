from __future__ import annotations

import io
import json
import math
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from backend.app.main import create_app

# What the STUMPY Motif Lab page (frontend/src/pages/analyzer-labs/StumpyMotifLabPage.tsx) sends.
# Overrides merge into the shipped settings key by key, and those run discord mode, so the lab
# has to ask for motif mode itself.
LAB_OVERRIDES = {
    "stumpy": {
        "implementation": {
            "library": "stumpy",
            "algorithm": "stump",
            "mode": "motif",
            "window_size": 20,
            "motif_count": 1,
            "profile_threshold": 2.0,
        },
        "finding_rules": {"max_motif_distance": 1.0, "min_confidence": 0.75},
    }
}


def _lab_series_csv(*, repeated: bool) -> bytes:
    """The lab's generator with its defaults: 180 points, seed 11, three copies of a 20-point shape."""
    state = 11

    def random() -> float:
        nonlocal state
        state = (1664525 * state + 1013904223) % 2**32
        return state / 2**32

    def gaussian() -> float:
        u1, u2 = max(random(), 1e-12), max(random(), 1e-12)
        return math.sqrt(-2 * math.log(u1)) * math.cos(2 * math.pi * u2)

    samples, window, repeats = 180, 20, 3
    values = [round(50 + gaussian() * 1.5, 3) for _ in range(samples)]
    if repeated:
        shape = [math.sin(i / (window - 1) * 2 * math.pi) * 12 + math.sin(i / (window - 1) * 4 * math.pi) * 12 * 0.35 for i in range(window)]
        spacing = (samples - window - 4) / repeats
        for order in range(repeats):
            start = min(max(2, round(spacing * order + spacing * 0.45)), samples - window - 1)
            for offset, value in enumerate(shape):
                values[start + offset] = round(50 + value, 3)
    begin = datetime(2026, 8, 24, tzinfo=timezone.utc)
    rows = ["timestamp,metric_name,value,service"]
    for index, value in enumerate(values):
        rows.append(f"{(begin + timedelta(minutes=5 * index)).strftime('%Y-%m-%dT%H:%M:%SZ')},synthetic_stumpy_value,{value},stumpy-lab")
    return "\n".join(rows).encode("utf-8")


def _run_lab(csv_bytes: bytes, overrides: dict) -> dict:
    app = create_app("sqlite+pysqlite:///:memory:")
    data = {
        "provider": "generic",
        "analyzer_id": "stumpy",
        "service": "stumpy-lab",
        "metric_name": "synthetic_stumpy_value",
        "interval": "5m",
        "analyzer_overrides": json.dumps(overrides),
    }
    with TestClient(app) as client:
        response = client.post(
            "/api/ingestion/csv-validate",
            data=data,
            files={"file": ("stumpy-motif-lab.csv", io.BytesIO(csv_bytes), "text/csv")},
        )
    assert response.status_code == 200, response.text
    return response.json()


def test_the_motif_lab_finds_a_repeated_shape() -> None:
    assert len(_run_lab(_lab_series_csv(repeated=True), LAB_OVERRIDES)["findings"]) == 1


def test_the_motif_lab_finds_nothing_in_plain_noise() -> None:
    assert _run_lab(_lab_series_csv(repeated=False), LAB_OVERRIDES)["findings"] == []


def test_without_motif_mode_the_shipped_discord_mode_runs_and_misses_the_repeated_shape() -> None:
    # Why the lab sends mode: before it did, the lab ran discord mode and found nothing (since 0.6.0).
    without_mode = json.loads(json.dumps(LAB_OVERRIDES))
    del without_mode["stumpy"]["implementation"]["mode"]
    assert _run_lab(_lab_series_csv(repeated=True), without_mode)["findings"] == []
