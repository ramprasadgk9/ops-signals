from __future__ import annotations

import numpy as np
import pandas as pd

from benchmark.nab import detector
from benchmark.nab.alert_budget import AlertBudget, best_under


def _timestamps(rows: int, freq: str) -> np.ndarray:
    # pandas keeps these at microsecond resolution; the gap between alerts must follow that unit.
    return pd.date_range("2026-01-01", periods=rows, freq=freq).as_unit("us").to_numpy()


def _budget(freq: str, scores: np.ndarray, windows: list[tuple[int, int]]) -> dict:
    budget = AlertBudget()
    values = np.full(len(scores), 10.0)
    budget.add_series(_timestamps(len(scores), freq), values, windows, {"live": scores})
    return budget.summary()


def test_flags_within_fifteen_minutes_are_one_alert() -> None:
    scores = np.zeros(400)
    scores[[200, 201, 202, 300]] = 0.9  # 5-minute rows: 200-202 is one burst, 300 another

    live = {p["setting"]: p for p in _budget("5min", scores, [(290, 310)])["curves"]["live"]}

    assert (live[0.5]["alerts"], live[0.5]["caught"]) == (2, 1)
    assert live[0.96]["alerts"] == 0


def test_consecutive_hourly_flags_are_one_alert() -> None:
    scores = np.zeros(400)
    scores[[200, 201, 202]] = 0.9

    live = {p["setting"]: p for p in _budget("1h", scores, [])["curves"]["live"]}

    assert live[0.5]["alerts"] == 1


def test_flags_in_the_probationary_period_do_not_count() -> None:
    scores = np.zeros(400)
    scores[10] = 0.9

    live = {p["setting"]: p for p in _budget("5min", scores, [])["curves"]["live"]}

    assert live[0.5]["alerts"] == 0


def test_a_wider_threshold_alerts_less() -> None:
    values = np.full(1000, 50.0)
    values[:150] = np.linspace(40, 60, 150)  # probation range 40-60
    values[500] = 64.0  # outside the plain limits, inside limits widened by 30% of the range
    values[800] = 90.0

    assert np.flatnonzero(detector.static_threshold_scores(values)).tolist() == [500, 800]
    assert np.flatnonzero(detector.static_threshold_scores(values, margin=0.3)).tolist() == [800]


def test_best_under_a_budget_takes_the_best_setting_that_fits() -> None:
    curve = [{"alerts": 100, "caught": 9}, {"alerts": 40, "caught": 7}, {"alerts": 10, "caught": 3}]

    assert best_under(curve, 50) == 7
    assert best_under(curve, 100) == 9
    assert best_under(curve, 5) is None
