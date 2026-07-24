from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from intelligence.normalize.normalizer import _parse_timestamps


def test_parse_timestamps_preserves_datetime_objects() -> None:
    start = datetime(2026, 7, 20, 12, 0, 0, tzinfo=timezone.utc)
    series = pd.Series([start, start + timedelta(seconds=15), start + timedelta(seconds=30)])

    parsed = _parse_timestamps(series, "prometheus")

    assert parsed.iloc[0].isoformat() == "2026-07-20T12:00:00+00:00"
    assert parsed.iloc[1].isoformat() == "2026-07-20T12:00:15+00:00"
    assert parsed.iloc[2].isoformat() == "2026-07-20T12:00:30+00:00"
    assert (parsed.iloc[1] - parsed.iloc[0]).total_seconds() == 15
