from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import ruptures as rpt


@dataclass
class RupturesResult:
    change_points: list[int]
    scores: dict[str, object]


def run_ruptures(values: pd.Series, algorithm: str, model: str, penalty: float, min_size: int, jump: int) -> RupturesResult:
    signal = np.asarray(pd.to_numeric(values, errors="coerce"), dtype=float).reshape(-1, 1)
    algo = (algorithm or "pelt").lower()
    model = (model or "l2").lower()
    min_size = max(2, int(min_size))
    jump = max(1, int(jump))

    if algo == "pelt":
        detector = rpt.Pelt(model=model, min_size=min_size, jump=jump).fit(signal)
        change_points = detector.predict(pen=penalty)
    elif algo == "binseg":
        detector = rpt.Binseg(model=model, min_size=min_size, jump=jump).fit(signal)
        change_points = detector.predict(pen=penalty)
    elif algo == "bottomup":
        detector = rpt.BottomUp(model=model, min_size=min_size, jump=jump).fit(signal)
        change_points = detector.predict(pen=penalty)
    else:
        raise ValueError(f"Unsupported algorithm: {algorithm}")

    change_points = [int(point) for point in change_points if int(point) < len(signal)]
    scores = {"algorithm": algo, "model": model, "penalty": float(penalty), "min_size": min_size, "jump": jump}
    return RupturesResult(change_points=change_points, scores=scores)
