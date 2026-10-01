from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from intelligence.drilldown import BreakdownWindow, breakdown_window, compute_breakdown, rewrite_for_breakdown
from intelligence.signals.schema import OperationalSignal

START = datetime(2026, 9, 1, 13, 0, tzinfo=timezone.utc)
CHANGE = START + timedelta(minutes=60)
END = START + timedelta(minutes=120)
TIMESTAMPS = pd.date_range(START, END, freq="1min")
WINDOW = BreakdownWindow(before_start=START, change_start=CHANGE, change_end=END)
PODS = ["a1", "x2", "k4", "m8", "p3", "z6"]


def _parts(levels: dict[str, tuple[float | None, float | None]], seed: int = 3) -> pd.DataFrame:
    """One series per pod: (level before the change, level after); None = pod absent then."""
    rng = np.random.default_rng(seed)
    rows = []
    for pod, (before, after) in levels.items():
        for timestamp in TIMESTAMPS:
            level = before if timestamp < CHANGE else after
            if level is None:
                continue
            rows.append({"part": pod, "timestamp": timestamp, "value": level + rng.normal(0, level * 0.02 + 1e-3)})
    return pd.DataFrame(rows)


def _signal(signal_type: str, start: datetime, end: datetime, **evidence) -> OperationalSignal:
    return OperationalSignal(
        signal_type=signal_type,
        analyzer_id=signal_type,
        metric_name="http_errors",
        service="checkout",
        env="prod",
        severity="high",
        confidence=0.9,
        start_time=start,
        end_time=end,
        summary="",
        evidence=evidence,
    )


# --- compute_breakdown, share mode (additive metrics) ---


def test_one_bad_pod_is_concentrated():
    levels = {pod: (0.2, 0.2) for pod in PODS}
    levels["x2"] = (0.2, 3.6)
    result = compute_breakdown(_parts(levels), label="pod", window=WINDOW, mode="share")

    assert result["status"] == "ok"
    assert result["spread"] == "concentrated"
    assert result["parts_changed"] == 1
    assert result["top"][0]["value"] == "x2"
    assert result["top"][0]["share"] > 0.9
    assert result["parts_total"] == 6


def test_every_pod_rising_is_widespread():
    levels = {pod: (0.2, 1.1) for pod in PODS}
    result = compute_breakdown(_parts(levels), label="pod", window=WINDOW, mode="share")

    assert result["spread"] == "widespread"
    assert all(0.1 < part["share"] < 0.25 for part in result["top"])


def test_every_pod_doubling_with_uneven_traffic_is_widespread_not_concentrated():
    # x2 takes most of the traffic, so it holds most of the increase - but every pod doubled.
    levels = {pod: (0.05, 0.10) for pod in PODS}
    levels["x2"] = (1.0, 2.0)
    result = compute_breakdown(_parts(levels), label="pod", window=WINDOW, mode="share")

    assert result["top"][0]["value"] == "x2"
    assert result["top"][0]["share"] > 0.7
    assert result["spread"] == "widespread"


def test_tiny_pod_with_big_relative_jump_does_not_hide_the_real_mover():
    levels = {pod: (1.0, 1.0) for pod in PODS}
    levels["x2"] = (1.0, 3.0)
    levels["k4"] = (0.001, 0.01)
    result = compute_breakdown(_parts(levels), label="pod", window=WINDOW, mode="share")

    assert result["spread"] == "concentrated"
    assert result["top"][0]["value"] == "x2"
    assert next(part for part in result["top"] if part["value"] == "k4")["moved"] is False


def test_two_of_six_pods_is_partial():
    levels = {pod: (0.2, 0.2) for pod in PODS}
    levels["x2"] = (0.2, 2.0)
    levels["k4"] = (0.2, 1.9)
    result = compute_breakdown(_parts(levels), label="pod", window=WINDOW, mode="share")

    assert result["spread"] == "partial"
    assert result["parts_changed"] == 2
    assert {part["value"] for part in result["top"][:2]} == {"x2", "k4"}


def test_new_pods_from_a_rollout_are_flagged_and_hold_the_change():
    levels = {pod: (0.2, 0.2) for pod in PODS[:4]}
    levels["n1"] = (None, 1.5)
    levels["n2"] = (None, 1.4)
    result = compute_breakdown(_parts(levels), label="pod", window=WINDOW, mode="share")

    assert result["new_parts"] == 2
    top_two = result["top"][:2]
    assert {part["value"] for part in top_two} == {"n1", "n2"}
    assert all(part["new"] for part in top_two)
    assert sum(part["share"] for part in top_two) > 0.9


def test_shares_sum_to_one_including_others():
    levels = {f"pod{index}": (1.0, 1.0 + index) for index in range(8)}
    result = compute_breakdown(_parts(levels), label="pod", window=WINDOW, mode="share")

    assert len(result["top"]) == 5
    assert result["others"]["count"] == 3
    total = sum(part["share"] for part in result["top"]) + result["others"]["share"]
    assert abs(total - 1.0) < 1e-3


def test_no_net_change_is_skipped_not_misreported():
    levels = {"a": (1.0, 2.0), "b": (2.0, 1.0)}
    result = compute_breakdown(_parts(levels, seed=0).assign(value=lambda f: f["value"].round(0)), label="pod", window=WINDOW, mode="share")

    assert result["status"] == "skipped"
    assert result["reason"] == "no_net_change"


def test_single_pod_is_skipped():
    result = compute_breakdown(_parts({"only": (1.0, 5.0)}), label="pod", window=WINDOW, mode="share")

    assert result["status"] == "skipped"
    assert result["reason"] == "single_part"


def test_empty_data_is_skipped():
    result = compute_breakdown(pd.DataFrame(columns=["part", "timestamp", "value"]), label="pod", window=WINDOW, mode="share")

    assert result == {**result, "status": "skipped", "reason": "no_data"}


# --- compute_breakdown, changed_parts mode (latency, averages) ---


def test_latency_one_slow_pod_is_concentrated_without_shares():
    levels = {pod: (0.12, 0.12) for pod in PODS}
    levels["x2"] = (0.12, 0.48)
    result = compute_breakdown(_parts(levels), label="pod", window=WINDOW, mode="changed_parts")

    assert result["spread"] == "concentrated"
    assert result["direction"] == "up"
    assert result["top"][0]["value"] == "x2"
    assert result["top"][0]["moved"] is True
    assert "share" not in result["top"][0]
    assert sum(part["moved"] for part in result["top"]) == 1


def test_latency_all_pods_slower_is_widespread():
    levels = {pod: (0.12, 0.30) for pod in PODS}
    result = compute_breakdown(_parts(levels), label="pod", window=WINDOW, mode="changed_parts")

    assert result["spread"] == "widespread"
    assert result["parts_changed"] == 6


def test_latency_drop_reports_direction_down():
    levels = {pod: (0.30, 0.30) for pod in PODS}
    levels["m8"] = (0.30, 0.05)
    result = compute_breakdown(_parts(levels), label="pod", window=WINDOW, mode="changed_parts")

    assert result["direction"] == "down"
    assert result["top"][0]["value"] == "m8"
    assert result["spread"] == "concentrated"


def test_latency_new_pod_compared_with_old_pods_baseline():
    levels = {pod: (0.12, 0.12) for pod in PODS[:4]}
    levels["n1"] = (None, 0.60)
    result = compute_breakdown(_parts(levels), label="pod", window=WINDOW, mode="changed_parts")

    assert result["top"][0]["value"] == "n1"
    assert result["top"][0]["new"] is True
    assert result["top"][0]["before"] is None
    assert result["spread"] == "concentrated"


# --- breakdown_window ---


def test_window_splits_at_change_point():
    signal = _signal("ruptures", START, END, change_point_time=CHANGE.isoformat())
    window = breakdown_window([signal], START, END)

    assert window == BreakdownWindow(before_start=START, change_start=CHANGE, change_end=END)


def test_window_for_short_anomaly_compares_with_stretch_before_it():
    anomaly_start = START + timedelta(minutes=90)
    anomaly_end = anomaly_start + timedelta(minutes=10)
    window = breakdown_window([_signal("anomaly", anomaly_start, anomaly_end)], START, END)

    assert window.change_start == anomaly_start
    assert window.change_end == anomaly_end
    assert window.before_start == anomaly_start - timedelta(minutes=90) / 4


def test_window_for_long_anomaly_uses_equally_long_stretch_before_it():
    anomaly_start = START + timedelta(minutes=80)
    anomaly_end = anomaly_start + timedelta(minutes=30)
    window = breakdown_window([_signal("anomaly", anomaly_start, anomaly_end)], START, END)

    assert window.before_start == anomaly_start - timedelta(minutes=30)


def test_window_ignores_gated_signals_that_did_not_match():
    unmatched = _signal("anomaly", START + timedelta(minutes=30), START + timedelta(minutes=35), finding_rule_matched=False)

    assert breakdown_window([unmatched], START, END) is None


def test_window_for_whole_series_trend_is_none():
    assert breakdown_window([_signal("trend", START, END)], START, END) is None


def test_window_change_point_at_series_edge_is_none():
    signal = _signal("ruptures", START, END, change_point_time=START.isoformat())

    assert breakdown_window([signal], START, END) is None


# --- rewrite_for_breakdown ---


def test_rewrite_sum_rate_is_share_mode():
    query = rewrite_for_breakdown('sum by (service) (rate(http_errors_total{service="checkout"}[5m]))', "pod")

    assert query.query == 'sum by (service, pod) (rate(http_errors_total{service="checkout"}[5m]))'
    assert query.mode == "share"


def test_rewrite_avg_is_changed_parts_mode():
    query = rewrite_for_breakdown('avg by (service) (process_cpu{service="checkout"})', "pod")

    assert query.query == 'avg by (service, pod) (process_cpu{service="checkout"})'
    assert query.mode == "changed_parts"


def test_rewrite_histogram_quantile_keeps_le():
    original = 'histogram_quantile(0.95, sum by (le, service) (rate(http_latency_bucket{service="checkout"}[5m])))'
    query = rewrite_for_breakdown(original, "pod")

    assert query.query == 'histogram_quantile(0.95, sum by (le, service, pod) (rate(http_latency_bucket{service="checkout"}[5m])))'
    assert query.mode == "changed_parts"


def test_rewrite_handles_parentheses_inside_label_values():
    query = rewrite_for_breakdown('sum by (service) (rate(errors_total{route="/a(b)"}[5m]))', "pod")

    assert query.query == 'sum by (service, pod) (rate(errors_total{route="/a(b)"}[5m]))'


def test_rewrite_rejects_unsupported_shapes():
    assert rewrite_for_breakdown('rate(errors_total{service="checkout"}[5m])', "pod") is None
    assert rewrite_for_breakdown('sum by (service) (rate(a[5m])) / sum by (service) (rate(b[5m]))', "pod") is None
    assert rewrite_for_breakdown('topk by (service) (3, errors_total)', "pod") is None
    assert rewrite_for_breakdown('sum by (service) (errors_total)', "bad-label") is None


def test_rewrite_rejects_query_already_grouped_by_label():
    assert rewrite_for_breakdown("sum by (service, pod) (errors_total)", "pod") is None
