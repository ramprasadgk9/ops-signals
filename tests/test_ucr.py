from __future__ import annotations

import numpy as np
import pytest

from benchmark.ucr import data, metrics
from benchmark.ucr.detector import DISCORD, MAX_JUMP, PRODUCT, estimate_period, run_method
from benchmark.ucr.run import _score, run_tasks


# The worked example on the archive's scoring slide: anomaly 114283-114350 (L = 68, so the
# 100-point floor applies on both sides).
def test_correct_region_matches_the_archives_worked_example() -> None:
    assert metrics.correct_region(114283, 114350) == (114183, 114450)
    assert metrics.is_correct(114184, 114283, 114350)
    assert metrics.is_correct(114449, 114283, 114350)
    assert not metrics.is_correct(114183, 114283, 114350)
    assert not metrics.is_correct(114450, 114283, 114350)
    assert not metrics.is_correct(None, 114283, 114350)


def test_long_anomalies_get_their_own_length_as_slack() -> None:
    assert metrics.correct_region(1000, 1499) == (500, 1999)


def test_default_rate_is_the_share_of_test_positions_counted_correct() -> None:
    # Test part is positions 1001..2000 (1000 positions). L = 101, so the correct region is
    # 1400..1700 (301 positions).
    assert metrics.default_rate(2000, 1000, 1500, 1600) == pytest.approx(301 / 1000)
    # The region is clipped to the test part.
    assert metrics.default_rate(2000, 1000, 1010, 1020) == pytest.approx(119 / 1000)


def test_file_names_give_labels_variant_and_domain() -> None:
    meta = data.parse_file_name("004_UCR_Anomaly_DISTORTEDBIDMC1_2500_5400_5600.txt")
    assert meta == {
        "number": 4,
        "name": "DISTORTEDBIDMC1",
        "source": "BIDMC1",
        "variant": "distorted",
        "domain": "Cardiovascular (ECG, blood pressure)",
        "train_end": 2500,
        "begin": 5400,
        "end": 5600,
    }
    assert data.parse_file_name("239_UCR_Anomaly_taichidbS0715Master_190037_593450_593514.txt")["domain"] == "Gait and motion"
    assert data.parse_file_name("150_UCR_Anomaly_Lab2Cmac011215EPG6_7000_12190_12420.txt")["domain"] == "Insect feeding (EPG)"
    assert data.parse_file_name("235_UCR_Anomaly_NOISEresperation2_30000_168250_168250.txt")["variant"] == "noise"
    with pytest.raises(ValueError):
        data.parse_file_name("not_a_series.txt")


def test_period_is_estimated_from_the_autocorrelation() -> None:
    t = np.arange(5000)
    assert abs(estimate_period(np.sin(2 * np.pi * t / 80)) - 80) <= 1
    assert estimate_period(np.random.default_rng(0).normal(size=5000)) == 100
    assert estimate_period(np.ones(5000)) == 100


def _write_series(tmp_path, values: np.ndarray, train_end: int, begin: int, end: int):
    path = tmp_path / f"001_UCR_Anomaly_synthetic_{train_end}_{begin}_{end}.txt"
    path.write_text("\n".join(f"{v:.6f}" for v in values), encoding="utf-8")
    return path


def _reversed_cycle(tmp_path):
    """A clean 50-point cycle with one cycle played backwards: same values, wrong shape."""
    t = np.arange(6000)
    values = np.sin(2 * np.pi * t / 50) + 0.3 * np.sin(4 * np.pi * t / 50)
    values[4500:4550] = values[4500:4550][::-1].copy()
    return _write_series(tmp_path, values, 2000, 4501, 4550)


def test_discord_finds_a_shape_anomaly_that_keeps_values_in_range(tmp_path) -> None:
    path = _reversed_cycle(tmp_path)
    series = data.load_series(path)

    result = _score(run_method(str(path), DISCORD), series)

    assert result["error"] is None
    assert result["window"] == 50
    assert result["correct"]


def test_max_jump_answers_with_the_row_after_the_biggest_step(tmp_path) -> None:
    values = np.zeros(3000)
    values[2500:] = 10.0
    path = _write_series(tmp_path, values, 1000, 2501, 2501)

    result = run_method(str(path), MAX_JUMP)

    assert result["row"] == 2500
    assert _score(result, data.load_series(path))["correct"]


def test_product_answers_after_the_training_part_or_not_at_all(tmp_path) -> None:
    rng = np.random.default_rng(7)
    values = rng.normal(0, 1, 6000)
    values[4800] = 40.0
    path = _write_series(tmp_path, values, 2000, 4801, 4801)

    result = _score(run_method(str(path), PRODUCT), data.load_series(path))

    assert result["error"] is None
    assert result["row"] is None or result["row"] >= 2000
    assert all(candidate["row"] >= 2000 for candidate in result["top_candidates"])


def test_worker_pool_runs_every_task(tmp_path) -> None:
    path = str(_reversed_cycle(tmp_path))

    results = run_tasks([(path, MAX_JUMP), (path, DISCORD)], workers=2, timeout=120)

    assert set(results) == {(path, MAX_JUMP), (path, DISCORD)}
    assert all(result["error"] is None for result in results.values())
