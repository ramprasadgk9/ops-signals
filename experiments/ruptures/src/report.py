from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from time import perf_counter


def build_report(
    dataset_name: str,
    inspection,
    quality_report,
    ruptures_config,
    normalization_explanation: str,
    execution_seconds: float,
    change_points: list[int],
    plot_paths: dict[str, str],
    label_comparison=None,
    observations: list[str] | None = None,
    recommended_configuration: str | None = None,
) -> str:
    lines = [
        f"# Ruptures Experiment Report: {dataset_name}",
        "",
        "## Dataset",
        f"- Rows: {inspection.rows}",
        f"- Columns: {inspection.columns}",
        f"- Timestamp column: {inspection.timestamp_column}",
        f"- Value column: {inspection.value_column}",
        f"- Sampling interval: {inspection.sampling_interval}",
        "",
        "## Configuration",
        f"- Algorithm: {ruptures_config.algorithm}",
        f"- Model: {ruptures_config.model}",
        f"- Penalty: {ruptures_config.penalty}",
        f"- Min size: {ruptures_config.min_size}",
        f"- Jump: {ruptures_config.jump}",
        f"- Normalization: {normalization_explanation}",
        "",
        "## Validation",
        f"- OK: {quality_report.ok}",
    ]
    if quality_report.issues:
        lines.append("- Issues:")
        lines.extend([f"  - {issue}" for issue in quality_report.issues])
    lines.extend([
        "",
        "## Results",
        f"- Execution time: {execution_seconds:.3f}s",
        f"- Detected change points: {change_points}",
    ])
    if label_comparison is not None:
        lines.extend([
            "",
            "## Label Comparison",
            f"- Expected anomaly windows: {label_comparison.expected_windows}",
            f"- Precision: {label_comparison.precision}",
            f"- Recall: {label_comparison.recall}",
            f"- F1: {label_comparison.f1}",
            f"- False positives: {label_comparison.false_positives}",
            f"- False negatives: {label_comparison.false_negatives}",
        ])
    lines.extend([
        "",
        "## Plots",
    ])
    for name, path in plot_paths.items():
        lines.append(f"- {name}: {path}")
    if observations:
        lines.extend(["", "## Observations"])
        lines.extend([f"- {obs}" for obs in observations])
    if recommended_configuration:
        lines.extend(["", "## Recommended Configuration", recommended_configuration])
    return "\n".join(lines) + "\n"


def save_report(report_text: str, output_path: str | Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report_text)
    return output_path
