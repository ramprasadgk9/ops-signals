from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

from backend.app.metric_analyzer_recommendations.service import MetricAnalyzerRecommendationService, MetricProfile


def _profile(values: list[float]) -> MetricProfile:
    """A minimal, honest MetricProfile - mean/stddev/variance computed straight from the same
    values used to build the timeseries, so the two inputs agree like they would in real use."""
    n = len(values)
    mean_value = sum(values) / n
    variance = sum((v - mean_value) ** 2 for v in values) / n
    return MetricProfile(
        sample_count=n,
        start_time=datetime.utcnow(),
        end_time=datetime.utcnow() + timedelta(minutes=n),
        sampling_interval_seconds=60,
        regular_sampling=True,
        missing_ratio=0.0,
        duplicate_timestamps=0,
        constant_value_ratio=0.0,
        mean=mean_value,
        stddev=variance**0.5,
        minimum=min(values),
        maximum=max(values),
        variance=variance,
        trend_slope=0.0,
        trend_strength=0.0,
        autocorrelation=None,
        seasonality_strength=0.0,
        sparsity=0.0,
        metric_behavior="unknown",
    )


def _timeseries(values: list[float]) -> list[tuple[datetime, float]]:
    start = datetime.utcnow()
    return [(start + timedelta(minutes=index), value) for index, value in enumerate(values)]


# A clean, obvious regime shift: steady ~50, then steady ~90.
SHIFT_SERIES = [50, 51, 49, 50, 52, 90, 91, 89, 90, 88, 91, 89]

# Same overall range (50-90), but just bouncing around one center - no real split anywhere.
NOISY_SERIES = [50, 90, 55, 85, 60, 80, 65, 75, 70, 72, 68, 74]


def test_shift_index_is_no_longer_blind_to_where_the_data_actually_changes():
    """Before the fix, shift_index was variance/mean on the whole series - both series here have
    a similar range (50-90) and would score similarly. The real per-split calculation should
    correctly tell them apart: high for a genuine regime change, low for pure noise."""
    service = MetricAnalyzerRecommendationService()

    shift_profile = service._build_router_profile(_profile(SHIFT_SERIES), _timeseries(SHIFT_SERIES))
    noisy_profile = service._build_router_profile(_profile(NOISY_SERIES), _timeseries(NOISY_SERIES))

    assert shift_profile.shift_index > 0.25
    assert noisy_profile.shift_index < shift_profile.shift_index
    # The old bug (variance/mean on the whole series) could not tell these two apart at all -
    # this is the actual behavior change the fix produces.
    assert shift_profile.shift_index - noisy_profile.shift_index > 0.15


def test_spikiness_is_actually_computed_and_wired_through_instead_of_hardcoded_zero():
    """Before the fix, spikiness was a hardcoded 0.0 for every series, no matter what - meaning
    pyod_outlier could never earn the ~0.30 of its score that comes from spikiness rules. This
    checks the wiring is correct - that whatever the real _spikiness() function returns for a
    series' values actually reaches the router profile - rather than asserting on a specific
    number from synthetic data, since the real function's own threshold calibration (a separate,
    deeper property of that algorithm, not of this fix) is its own concern."""
    service = MetricAnalyzerRecommendationService()
    series = list(range(20))

    with patch("backend.app.metric_analyzer_recommendations.service._spikiness", return_value=(0.73, 2, 1)) as mock_spikiness:
        profile = service._build_router_profile(_profile([float(v) for v in series]), _timeseries([float(v) for v in series]))

    mock_spikiness.assert_called_once()
    assert profile.spikiness == 0.73


def test_no_timeseries_falls_back_to_the_previous_safe_defaults():
    """The preliminary chat path (no real sample selected yet) has no underlying data at all -
    spikiness must stay 0.0 rather than fabricate a number from nothing."""
    service = MetricAnalyzerRecommendationService()
    profile = service._build_router_profile(_profile(SHIFT_SERIES), None)

    assert profile.spikiness == 0.0
