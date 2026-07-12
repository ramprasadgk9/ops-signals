from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from ops_signals.config import load_config
from ops_signals.daily_report import build_daily_report
from ops_signals.findings.schema import OperationalFinding
from ops_signals.storage.postgres_store import PostgresStore


def _load_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--config", default="config.yaml")
    args, _ = parser.parse_known_args()
    return args


def _interval_to_timedelta(interval: str) -> pd.Timedelta | None:
    try:
        normalized = interval.replace("m", "min") if interval.endswith("m") else interval
        return pd.to_timedelta(normalized)
    except (TypeError, ValueError):
        return None


def _apply_filters(dataframe: pd.DataFrame) -> pd.DataFrame:
    if dataframe.empty:
        return dataframe

    metric_name = st.sidebar.selectbox("metric_name", ["All", *sorted(dataframe["metric_name"].dropna().unique())])
    service = st.sidebar.selectbox("service", ["All", *sorted(dataframe["service"].dropna().astype(str).unique())])
    category = st.sidebar.selectbox("category", ["All", *sorted(dataframe["category"].dropna().astype(str).unique())])
    health_status = st.sidebar.selectbox("health_status", ["All", *sorted(dataframe["health_status"].dropna().astype(str).unique())])

    filtered = dataframe.copy()
    for column, value in {
        "metric_name": metric_name,
        "service": service,
        "category": category,
        "health_status": health_status,
    }.items():
        if value != "All":
            filtered = filtered[filtered[column].astype(str) == str(value)]
    return filtered


def _prepare_points(points: pd.DataFrame) -> pd.DataFrame:
    if points.empty:
        return points
    prepared = points.copy()
    prepared["timestamp"] = pd.to_datetime(prepared["timestamp"], utc=True, errors="coerce")
    prepared["value"] = pd.to_numeric(prepared["value"], errors="coerce")
    return prepared.dropna(subset=["timestamp", "value"]).sort_values("timestamp")


def _summarize_points(points: pd.DataFrame, expected_interval: pd.Timedelta | None) -> dict[str, Any]:
    if points.empty:
        return {}

    start_time = points["timestamp"].min()
    end_time = points["timestamp"].max()
    duration = end_time - start_time
    observed_points = len(points)

    cadence = points["timestamp"].sort_values().diff().median()
    cadence_minutes = (cadence.total_seconds() / 60.0) if pd.notna(cadence) else None

    missing_points = 0
    if expected_interval is not None and expected_interval.total_seconds() > 0:
        group_columns = ["metric_name", "service", "env"]
        for _, group in points.groupby(group_columns, dropna=False):
            g_start = group["timestamp"].min()
            g_end = group["timestamp"].max()
            expected_count = int(((g_end - g_start) / expected_interval)) + 1
            missing_points += max(expected_count - len(group), 0)

    return {
        "start_time": start_time,
        "end_time": end_time,
        "duration_hours": round(duration.total_seconds() / 3600.0, 2),
        "observed_points": observed_points,
        "cadence_minutes": round(cadence_minutes, 2) if cadence_minutes is not None else None,
        "missing_points": missing_points,
        "metric_count": int(points["metric_name"].nunique()),
        "series_count": int(points.groupby(["metric_name", "service", "env"], dropna=False).ngroups),
    }


def _primary_series(points: pd.DataFrame) -> pd.DataFrame:
    if points.empty:
        return points
    group_columns = ["metric_name", "service", "env"]
    primary_key = points.groupby(group_columns, dropna=False).size().sort_values(ascending=False).index[0]
    key_values = primary_key if isinstance(primary_key, tuple) else (primary_key,)
    series = points.copy()
    for column, value in zip(group_columns, key_values):
        if pd.isna(value):
            series = series[series[column].isna()]
        else:
            series = series[series[column].astype(str) == str(value)]
    return series.sort_values("timestamp")


def _plain_language_summary(points: pd.DataFrame) -> str:
    if points.empty:
        return "No normalized data is available yet. Run the pipeline to populate input time-series points."

    ordered = points.sort_values("timestamp").reset_index(drop=True)
    midpoint = len(ordered) // 2
    first_half_mean = float(ordered.iloc[:midpoint]["value"].mean()) if midpoint > 0 else float(ordered["value"].mean())
    second_half_mean = float(ordered.iloc[midpoint:]["value"].mean())
    baseline_shift = ((second_half_mean - first_half_mean) / max(abs(first_half_mean), 1e-9)) * 100.0

    x_values = pd.Series(range(len(ordered)), dtype=float)
    slope = float(pd.Series(ordered["value"], dtype=float).cov(x_values) / x_values.var()) if len(ordered) > 1 else 0.0
    trend_direction = "upward" if slope > 0 else "downward"

    stddev = float(ordered["value"].std(ddof=0))
    zscore_count = 0
    if stddev > 0:
        zscores = (ordered["value"] - float(ordered["value"].mean())) / stddev
        zscore_count = int((zscores.abs() >= 3.0).sum())

    return (
        f"Primary metric moved from an early-window average of {first_half_mean:.1f} to a later-window average of "
        f"{second_half_mean:.1f} ({baseline_shift:.1f}% change). The overall direction is {trend_direction}. "
        f"There are {zscore_count} point(s) that look like strong outliers at |z| >= 3."
    )


def _series_filter(points: pd.DataFrame, metric_name: str, service: str, env: str) -> pd.DataFrame:
    selected = points.copy()
    if metric_name != "All":
        selected = selected[selected["metric_name"].astype(str) == metric_name]
    if service != "All":
        selected = selected[selected["service"].astype(str) == service]
    if env != "All":
        selected = selected[selected["env"].astype(str) == env]
    return selected.sort_values("timestamp")


def _points_for_finding(points: pd.DataFrame, detail: pd.Series) -> pd.DataFrame:
    if points.empty:
        return points

    view = points.copy()
    view["timestamp"] = pd.to_datetime(view["timestamp"], utc=True, errors="coerce")
    view = view[view["metric_name"].astype(str) == str(detail["metric_name"])]

    if pd.notna(detail.get("service")):
        view = view[view["service"].astype(str) == str(detail["service"])]
    if pd.notna(detail.get("env")):
        view = view[view["env"].astype(str) == str(detail["env"])]

    start_time = pd.to_datetime(detail.get("analysis_window_start"), utc=True, errors="coerce")
    end_time = pd.to_datetime(detail.get("analysis_window_end"), utc=True, errors="coerce")
    if pd.notna(start_time):
        view = view[view["timestamp"] >= start_time]
    if pd.notna(end_time):
        view = view[view["timestamp"] <= end_time]

    return view.sort_values("timestamp")


def _finding_summary_cards(report) -> None:
    total_col, health_col, critical_col, significant_col, normal_col, metric_col = st.columns(6)
    total_col.metric("Top findings", int(len(report.top_findings)))
    health_col.metric("Overall Health Score", report.overall_health_score)
    critical_col.metric("Critical Findings", report.critical_findings)
    significant_col.metric("Significant Findings", report.significant_findings)
    normal_col.metric("Normal Findings", report.normal_findings)
    metric_col.metric("Metrics Analysed", report.metrics_analysed)


def _finding_filters(dataframe: pd.DataFrame) -> pd.DataFrame:
    if dataframe.empty:
        return dataframe

    metric_name = st.sidebar.selectbox("metric_name", ["All", *sorted(dataframe["metric_name"].dropna().astype(str).unique())], key="finding_metric")
    service = st.sidebar.selectbox("service", ["All", *sorted(dataframe["service"].dropna().astype(str).unique())], key="finding_service")
    category = st.sidebar.selectbox("category", ["All", *sorted(dataframe["category"].dropna().astype(str).unique())], key="finding_category")
    health_status = st.sidebar.selectbox("health_status", ["All", *sorted(dataframe["health_status"].dropna().astype(str).unique())], key="finding_health")

    filtered = dataframe.copy()
    for column, value in {
        "metric_name": metric_name,
        "service": service,
        "category": category,
        "health_status": health_status,
    }.items():
        if value != "All":
            filtered = filtered[filtered[column].astype(str) == str(value)]
    return filtered


def main() -> None:
    args = _load_args()
    config = load_config(Path(args.config))
    store = PostgresStore(config)

    st.set_page_config(page_title="ops-signals", layout="wide")
    st.title("ops-signals")
    st.caption("Batch Operational Signal Engine MVP")

    findings = store.fetch_findings()
    normalized_points = _prepare_points(store.fetch_normalized_points())

    if findings.empty and normalized_points.empty:
        st.info("No normalized points or findings found. Run the batch pipeline first.")
        return

    report = build_daily_report([OperationalFinding(**row) for row in findings.to_dict(orient="records")], normalized_points) if not findings.empty else build_daily_report([], normalized_points)

    overview_tab, findings_tab = st.tabs(["Operational Intelligence Report", "Findings Explorer"])

    with overview_tab:
        st.subheader("Operational Intelligence Report")
        if normalized_points.empty:
            st.info("No normalized time-series points found yet. Run the pipeline to see an input overview.")
        else:
            expected_interval = _interval_to_timedelta(config.input.interval)
            summary = _summarize_points(normalized_points, expected_interval)

            col1, col2, col3 = st.columns(3)
            col1.metric("Start time", str(summary["start_time"]))
            col2.metric("End time", str(summary["end_time"]))
            col3.metric("Duration (hours)", summary["duration_hours"])

            col4, col5, col6 = st.columns(3)
            col4.metric("Observed points", summary["observed_points"])
            col5.metric("Median cadence (minutes)", summary["cadence_minutes"] if summary["cadence_minutes"] is not None else "N/A")
            col6.metric("Estimated missing points", summary["missing_points"])

            col7, col8 = st.columns(2)
            col7.metric("Metrics", summary["metric_count"])
            col8.metric("Metric-service-env series", summary["series_count"])

            _finding_summary_cards(report)

            answer_col1, answer_col2 = st.columns(2)
            answer_col1.markdown(f"**What changed yesterday?** {report.answers['what_changed_yesterday']}")
            answer_col1.markdown(f"**Did anything unusual happen?** {report.answers['did_anything_unusual_happen']}")
            answer_col2.markdown(f"**What should I investigate first?** {report.answers['what_should_i_investigate_first']}")
            answer_col2.markdown(f"**Is this behaviour new or expected?** {report.answers['is_this_behavior_new_or_expected']}")
            st.markdown(f"**Has this happened before?** {report.answers['has_this_happened_before']}")

            st.info(_plain_language_summary(_primary_series(normalized_points)))

            metric_options = ["All", *sorted(normalized_points["metric_name"].dropna().astype(str).unique())]
            service_options = ["All", *sorted(normalized_points["service"].dropna().astype(str).unique())]
            env_options = ["All", *sorted(normalized_points["env"].dropna().astype(str).unique())]

            selector_col1, selector_col2, selector_col3 = st.columns(3)
            selected_metric = selector_col1.selectbox("metric_name", metric_options, key="overview_metric")
            selected_service = selector_col2.selectbox("service", service_options, key="overview_service")
            selected_env = selector_col3.selectbox("env", env_options, key="overview_env")

            selected_points = _series_filter(normalized_points, selected_metric, selected_service, selected_env)
            if selected_points.empty:
                st.warning("No points match the selected filters.")
            else:
                st.line_chart(selected_points[["timestamp", "value"]].set_index("timestamp"), width="stretch")
                with st.expander("Preview normalized rows"):
                    st.dataframe(
                        selected_points[
                            ["timestamp", "metric_name", "value", "service", "env", "host", "namespace", "pod"]
                        ],
                        width="stretch",
                        hide_index=True,
                    )

    with findings_tab:
        st.subheader("Top Findings")
        if findings.empty:
            st.info("No operational findings found for the current dataset.")
            return

        filtered = _finding_filters(findings)

        if filtered.empty:
            st.info("No findings match the current filters.")
            return

        st.dataframe(
            filtered[
                [
                    "id",
                    "title",
                    "metric_name",
                    "service",
                    "category",
                    "health_status",
                    "importance_score",
                    "investigation_priority",
                ]
            ],
            width="stretch",
            hide_index=True,
        )

        left, right = st.columns([2, 1])
        with left:
            selected_id = st.selectbox("Finding id", filtered["id"].tolist())
            detail = filtered[filtered["id"] == selected_id].iloc[0]
            st.write("Summary")
            st.write(detail["summary"])
            st.write("Evidence")
            st.json(detail["comparison_json"])

            st.write("Contributing Signals")
            detail_signal_ids = detail["signal_ids"]
            if isinstance(detail_signal_ids, str):
                detail_signal_ids = [detail_signal_ids]
            contributing_signals = store.fetch_signals_for_ids(list(detail_signal_ids))
            if contributing_signals.empty:
                st.info("No contributing signals found.")
            else:
                st.dataframe(
                    contributing_signals[
                        [
                            "signal_id",
                            "signal_type",
                            "severity",
                            "confidence",
                            "importance_score",
                            "summary",
                        ]
                    ],
                    width="stretch",
                    hide_index=True,
                )

        with right:
            st.write("Historical Comparison")
            st.json(detail["comparison_json"])

            st.write("Metric Graph")
            signal_points = _points_for_finding(normalized_points, detail)
            if signal_points.empty:
                st.info("No normalized points found for the selected finding window.")
            else:
                chart_data = signal_points[["timestamp", "value"]].set_index("timestamp")
                st.line_chart(chart_data, width="stretch")


if __name__ == "__main__":
    main()
