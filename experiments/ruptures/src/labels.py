from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class LabelComparison:
    expected_windows: list[tuple[pd.Timestamp, pd.Timestamp]]
    detected_points: list[pd.Timestamp]
    precision: float | None
    recall: float | None
    f1: float | None
    false_positives: list[pd.Timestamp]
    false_negatives: list[tuple[pd.Timestamp, pd.Timestamp]]


def load_labels(dataframe: pd.DataFrame, timestamp_column: str, label_column: str | None = None, anomaly_start_column: str | None = None, anomaly_end_column: str | None = None) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    if label_column and label_column in dataframe.columns:
        mask = dataframe[label_column].astype(str).str.lower().isin({"1", "true", "yes", "anomaly", "outlier"})
        if mask.any():
            ts = pd.to_datetime(dataframe.loc[mask, timestamp_column], utc=True, errors="coerce")
            return [(ts.iloc[0], ts.iloc[-1])]
    if anomaly_start_column and anomaly_end_column and anomaly_start_column in dataframe.columns and anomaly_end_column in dataframe.columns:
        starts = pd.to_datetime(dataframe[anomaly_start_column], utc=True, errors="coerce")
        ends = pd.to_datetime(dataframe[anomaly_end_column], utc=True, errors="coerce")
        return [(s, e) for s, e in zip(starts, ends) if pd.notna(s) and pd.notna(e)]
    return []


def compare_with_labels(dataframe: pd.DataFrame, timestamp_column: str, change_points: list[int], label_windows: list[tuple[pd.Timestamp, pd.Timestamp]]) -> LabelComparison:
    timestamps = pd.to_datetime(dataframe[timestamp_column], utc=True, errors="coerce").reset_index(drop=True)
    detected_points = [timestamps.iloc[point] for point in change_points[:-1] if 0 <= point < len(timestamps)]
    matched = set()
    true_positives = 0
    false_positives: list[pd.Timestamp] = []

    for point in detected_points:
        found = False
        for idx, (start, end) in enumerate(label_windows):
            if idx in matched:
                continue
            if start <= point <= end:
                matched.add(idx)
                true_positives += 1
                found = True
                break
        if not found:
            false_positives.append(point)

    false_negatives = [window for idx, window in enumerate(label_windows) if idx not in matched]
    precision = true_positives / len(detected_points) if detected_points else None
    recall = true_positives / len(label_windows) if label_windows else None
    f1 = None
    if precision is not None and recall not in (None, 0) and (precision + recall):
        f1 = 2 * precision * recall / (precision + recall)
    return LabelComparison(
        expected_windows=label_windows,
        detected_points=detected_points,
        precision=precision,
        recall=recall,
        f1=f1,
        false_positives=false_positives,
        false_negatives=false_negatives,
    )
