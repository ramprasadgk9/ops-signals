from __future__ import annotations

import numpy as np
import pytest

from benchmark.tcpd import metrics
from benchmark.tcpd.data import TcpdSeries
from benchmark.tcpd.detector import run_series


# The expected values are the doctest examples in TCPDBench's analysis/scripts/metrics.py.
@pytest.mark.parametrize(
    ("annotations", "predictions", "expected"),
    [
        ({1: [10, 20], 2: [11, 20], 3: [10], 4: [0, 5]}, [10, 20], 1.0),
        ({1: [], 2: [10], 3: [50]}, [10], 0.9090909090909091),
        ({1: [], 2: [10], 3: [50]}, [], 0.8),
    ],
)
def test_f_measure_matches_tcpdbench(annotations, predictions, expected) -> None:
    assert metrics.f_measure(annotations, predictions) == pytest.approx(expected, abs=1e-12)


@pytest.mark.parametrize(
    ("annotations", "predictions", "n_obs", "expected"),
    [
        ({1: [10, 20], 2: [10], 3: [0, 5]}, [10, 20], 45, 0.7962962962962963),
        ({1: [], 2: [10], 3: [40]}, [10], 45, 0.7954144620811286),
        ({1: [], 2: [10], 3: [40]}, [], 45, 0.8189300411522634),
    ],
)
def test_covering_matches_tcpdbench(annotations, predictions, n_obs, expected) -> None:
    assert metrics.covering(annotations, predictions, n_obs) == pytest.approx(expected, abs=1e-12)


def test_true_positives_never_double_count_a_prediction() -> None:
    assert metrics.true_positives({1, 10, 20, 23}, {1, 3, 5, 8, 20}) == {1, 10, 20}


def test_a_clean_mid_series_step_is_found_within_tcpds_margin() -> None:
    rng = np.random.default_rng(3)
    values = np.concatenate([rng.normal(10, 0.2, 100), rng.normal(20, 0.2, 100)])
    series = TcpdSeries(name="step", long_name="step", values=values, annotations={"a": [100], "b": [100]})

    run = run_series(series)

    assert run.direct_error is None
    assert run.product_error is None
    assert len(run.direct_cps) == 1
    assert abs(run.direct_cps[0] - 100) <= metrics.MARGIN
    assert metrics.f_measure(series.annotations, run.direct_cps) == 1.0
