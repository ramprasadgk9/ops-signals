from __future__ import annotations

from collections import Counter


def summarize_signals(signals: list[dict]) -> dict:
    counts = Counter(sig.get("signal_type", "unknown") for sig in signals)
    severities = Counter(sig.get("severity", "low") for sig in signals)
    avg_conf = sum(float(sig.get("confidence") or 0.0) for sig in signals) / max(len(signals), 1)
    top = sorted(signals, key=lambda s: float(s.get("importance_score") or 0), reverse=True)
    return {
        "counts": counts,
        "severities": severities,
        "avg_conf": round(avg_conf, 3),
        "top": top,
        "signal_ids": [str(sig.get("id")) for sig in top],
    }
