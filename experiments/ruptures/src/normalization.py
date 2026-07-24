from __future__ import annotations

import pandas as pd


def normalize_signal(series: pd.Series, method: str) -> pd.Series:
    method = (method or "none").lower()
    values = pd.to_numeric(series, errors="coerce")
    if method == "none":
        return values
    if method == "standard":
        std = float(values.std(ddof=0))
        if std == 0:
            return values * 0.0
        return (values - values.mean()) / std
    if method == "minmax":
        min_value = float(values.min())
        max_value = float(values.max())
        span = max_value - min_value
        if span == 0:
            return values * 0.0
        return (values - min_value) / span
    raise ValueError(f"Unsupported normalization method: {method}")


def explain_normalization(method: str) -> str:
    method = (method or "none").lower()
    if method == "none":
        return "No normalization is applied. This is usually fine when the absolute metric scale is meaningful and stable."
    if method == "standard":
        return "Standard scaling centers the signal and puts it in standard deviation units. It helps when amplitude differs across metrics or runs."
    if method == "minmax":
        return "Min-max scaling compresses values to [0, 1]. It is useful for shape comparison, but can hide magnitude differences that Ruptures may care about."
    return "Unknown normalization method."
