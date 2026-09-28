"""Score Ops Signals on the Turing Change Point Dataset against the paper's published methods.

    .venv/bin/python -m benchmark.run_all --suites tcpd

Before anything is scored, the suite recomputes every published score in TCPDBench's summaries with
the ported metrics and checks they match, and reproduces the paper's published univariate averages
from its per-series scores. Ops Signals and the 14 published methods are then compared on exactly
the same series: the paper's univariate evaluation set, limited to the series that ship as data
(the rest need TCPD's download scripts, which this harness doesn't run).

Averages follow the paper's default setting ("zero_no_coal"): a failure scores 0 on that series.
The published numbers are the paper's "default" experiment - each method with its default
parameters, no per-series tuning - which is the fair comparison for Ops Signals' default config.
"""

from __future__ import annotations

import statistics
from dataclasses import asdict
from typing import Any

import numpy as np

from benchmark.methods import ALL_ANALYZERS, LABELS, ROUTER_PICKS
from benchmark.tcpd import data, metrics
from benchmark.tcpd.detector import CHANGE_SIGNAL_TYPES, DIRECT_ANALYZER, run_series, series_frame

OURS = {
    "product": f"{LABELS[ROUTER_PICKS]} (product)",
    ALL_ANALYZERS: LABELS[ALL_ANALYZERS],
    "direct": f"Ops Signals, {DIRECT_ANALYZER} only",
}
SERIES_POINTS = 360


def run_tcpd_suite() -> dict[str, Any]:
    tcpd_dir, bench_dir = data.ensure_tcpd()
    validation = validate_port(bench_dir)
    published = data.published_default_scores(bench_dir)
    evaluation = data.evaluation_set(tcpd_dir)
    available = [name for name in evaluation if data.is_available(tcpd_dir, name)]
    unavailable = [name for name in evaluation if name not in available]

    rows = []
    for name in available:
        series = data.load_series(tcpd_dir, name)
        run = run_series(series)
        scores = {}
        for mode, cps, error in (
            ("product", run.product_cps, run.product_error),
            (ALL_ANALYZERS, run.all_cps, run.all_error),
            ("direct", run.direct_cps, run.direct_error),
        ):
            if error:
                scores[mode] = {"f1": 0.0, "precision": None, "recall": None, "cover": 0.0}
                continue
            f1, precision, recall = metrics.f_measure(series.annotations, cps, return_PR=True)
            scores[mode] = {"f1": f1, "precision": precision, "recall": recall, "cover": metrics.covering(series.annotations, cps, len(series.values))}
        record = asdict(run)
        rows.append(
            {
                **record,
                "long_name": series.long_name,
                "annotations": series.annotations,
                "annotated_cp_counts": sorted(len(v) for v in series.annotations.values()),
                "scores": scores,
                "published": {metric: published[metric].get(name, {}) for metric in ("f1", "cover")},
                "plot": _plot_points(series),
            }
        )

    return {
        "tcpd": {"repository": data.TCPD_REPOSITORY, "commit": data.TCPD_COMMIT},
        "tcpdbench": {"repository": data.TCPDBENCH_REPOSITORY, "commit": data.TCPDBENCH_COMMIT},
        "validation": validation,
        "settings": {
            "margin": metrics.MARGIN,
            "change_signal_types": sorted(CHANGE_SIGNAL_TYPES),
            "direct_analyzer": DIRECT_ANALYZER,
            "missing_strategy": "zero_no_coal",
        },
        "evaluation_set_size": len(evaluation),
        "evaluated": available,
        "unavailable": unavailable,
        "leaderboard": _leaderboard(rows, published, available),
        "cost": {
            mode: {
                "seconds": round(sum(row["seconds"].get(mode, 0.0) for row in rows), 3),
                "analyzer_runs": sum(len(row[key]) for row in rows) if key else len(rows),
            }
            for mode, key in (("product", "executed_analyzers"), (ALL_ANALYZERS, "all_executed_analyzers"), ("direct", None))
        },
        "leaderboard_full_published": _published_averages(published, evaluation),
        "series": rows,
    }


def validate_port(bench_dir) -> dict[str, Any]:
    """Recompute every published score from the published change points with the ported metrics."""
    checked = mismatches = 0
    worst = 0.0
    for path in sorted((bench_dir / "analysis" / "output" / "summaries").glob("summary_*.json")):
        summary = data.published_summary(bench_dir, path.stem[len("summary_"):])
        annotations, n_obs = summary["annotations"], summary["dataset_nobs"]
        for runs in summary["results"].values():
            for result in runs:
                if result.get("status") != "SUCCESS" or not result.get("scores"):
                    continue
                cps = result["cplocations"]
                f1, precision, recall = metrics.f_measure(annotations, cps, return_PR=True)
                cover = metrics.covering(annotations, cps, n_obs)
                for got, expected in zip((f1, precision, recall, cover), (result["scores"][k] for k in ("f1", "precision", "recall", "cover"))):
                    difference = abs(got - expected)
                    worst = max(worst, difference)
                    checked += 1
                    mismatches += difference > 1e-9
    evaluation = data.evaluation_set(bench_dir.parent / "tcpd")
    averages = _published_averages(data.published_default_scores(bench_dir), evaluation)
    return {
        "scores_checked": checked,
        "mismatches": mismatches,
        "worst_difference": worst,
        "published_averages_recomputed": {m: averages[m] for m in ("binseg", "zero")},
    }


def _leaderboard(rows: list[dict[str, Any]], published: dict[str, Any], names: list[str]) -> list[dict[str, Any]]:
    board = []
    for mode, label in OURS.items():
        board.append(
            {
                "method": label,
                "key": mode,
                "ours": True,
                "f1": statistics.mean(row["scores"][mode]["f1"] for row in rows) if rows else None,
                "cover": statistics.mean(row["scores"][mode]["cover"] for row in rows) if rows else None,
            }
        )
    averages = _published_averages(published, names)
    board.extend({"method": method, "ours": False, **averages[method]} for method in data.PUBLISHED_METHODS)
    return sorted(board, key=lambda row: -(row["f1"] or 0))


def _published_averages(published: dict[str, Any], names: list[str]) -> dict[str, dict[str, float]]:
    return {
        method: {
            metric: round(statistics.mean((published[metric][name].get(method) or 0.0) for name in names), 6)
            for metric in ("f1", "cover")
        }
        for method in data.PUBLISHED_METHODS
    }


def _plot_points(series: data.TcpdSeries) -> list[list[Any]]:
    frame = series_frame(series)
    bucket = max(1, -(-len(frame) // SERIES_POINTS))
    grouped = frame.groupby(frame.index // bucket).agg(timestamp=("timestamp", "first"), value=("value", "mean"))
    return [
        [row.timestamp.isoformat(), None if np.isnan(row.value) else round(float(row.value), 6), f"row {index * bucket}"]
        for index, row in enumerate(grouped.itertuples())
    ]
