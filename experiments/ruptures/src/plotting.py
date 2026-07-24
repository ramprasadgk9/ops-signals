from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


def save_raw_plot(dataframe: pd.DataFrame, timestamp_column: str, value_column: str, output_path: str | Path, title: str) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    timestamps = pd.to_datetime(dataframe[timestamp_column], utc=True, errors="coerce")
    values = pd.to_numeric(dataframe[value_column], errors="coerce")

    fig, ax = plt.subplots(figsize=(14, 5))
    ax.plot(timestamps, values, color="#1f77b4", linewidth=1.5, label="signal")
    ax.set_title(title)
    ax.set_xlabel("Time")
    ax.set_ylabel(value_column)
    ax.grid(True, alpha=0.3)
    ax.text(0.01, 0.98, f"min={values.min():.4g}\nmax={values.max():.4g}\nmean={values.mean():.4g}", transform=ax.transAxes, va="top", ha="left", fontsize=9, bbox={"boxstyle": "round", "facecolor": "white", "alpha": 0.8})
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(output_path, dpi=180)
    plt.close(fig)
    return output_path


def save_change_point_plot(dataframe: pd.DataFrame, timestamp_column: str, value_column: str, change_points: list[int], output_path: str | Path, title: str) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    timestamps = pd.to_datetime(dataframe[timestamp_column], utc=True, errors="coerce").reset_index(drop=True)
    values = pd.to_numeric(dataframe[value_column], errors="coerce").reset_index(drop=True)

    fig, ax = plt.subplots(figsize=(14, 5))
    ax.plot(timestamps, values, color="#1f77b4", linewidth=1.5, label="signal")
    for point in change_points[:-1]:
        if 0 <= point < len(timestamps):
            ts = timestamps.iloc[point]
            ax.axvline(ts, color="#d62728", linestyle="--", linewidth=1.5)
            ax.annotate(str(ts), xy=(ts, values.max()), xytext=(5, -15), textcoords="offset points", rotation=90, fontsize=8, color="#d62728")
    ax.set_title(title)
    ax.set_xlabel("Time")
    ax.set_ylabel(value_column)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper right")
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(output_path, dpi=180)
    plt.close(fig)
    return output_path


def save_comparison_plot(results: list[tuple[str, pd.DataFrame, list[int]]], timestamp_column: str, value_column: str, output_path: str | Path, title: str) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(len(results), 1, figsize=(14, max(4, 4 * len(results))), sharex=True)
    if len(results) == 1:
        axes = [axes]
    for ax, (label, frame, points) in zip(axes, results):
        timestamps = pd.to_datetime(frame[timestamp_column], utc=True, errors="coerce").reset_index(drop=True)
        values = pd.to_numeric(frame[value_column], errors="coerce").reset_index(drop=True)
        ax.plot(timestamps, values, color="#1f77b4", linewidth=1.2)
        for point in points[:-1]:
            if 0 <= point < len(timestamps):
                ax.axvline(timestamps.iloc[point], color="#d62728", linestyle="--", linewidth=1.0)
        ax.set_title(label)
        ax.grid(True, alpha=0.3)
    axes[-1].set_xlabel("Time")
    axes[len(axes)//2].set_ylabel(value_column)
    fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(output_path, dpi=180)
    plt.close(fig)
    return output_path
